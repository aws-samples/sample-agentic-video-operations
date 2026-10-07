import { applyChartFormatters } from "./chartFormatters";
import { logEvent, logFailure } from "./logMetadata";
import {
  BedrockRuntimeClient,
  InvokeModelCommand,
} from "@aws-sdk/client-bedrock-runtime";
import { createAwsClient } from "./AwsAuth.js";
import {
  extractBetweenTags,
  removeCharFromStartAndEnd,
} from "./Utils.js";
import { CHART_MODEL_ID } from "../env.js";
import { CHART_PROMPT } from "../prompts/chartPrompt.js";

/**
 * Generates a chart based on answer and data
 * @param {Object} answer - Answer object containing text
 * @returns {Object} Chart configuration or rationale for no chart
 */
export const generateChart = async (answer) => {
  if (!CHART_MODEL_ID) {
    throw new Error("Set CHART_MODEL_ID before building the Amplify application.");
  }
  const bedrock = await createAwsClient(BedrockRuntimeClient);
  let query_results = "";
  for (let i = 0; i < answer.queryResults.length; i++) {
    query_results +=
      JSON.stringify(answer.queryResults[i].query_results) + "\n";
  }

  // Extract text content from the answer's text array
  const answerText = Array.isArray(answer.text)
    ? answer.text
        .filter((item) => item.type === "text")
        .map((item) => item.content)
        .join("\n")
    : String(answer.text || "");

  // Prepare the prompt
  let new_chart_prompt = CHART_PROMPT.replace(
    /<<answer>>/i,
    answerText
  ).replace(/<<data_sources>>/i, query_results);

  const payload = {
    anthropic_version: "bedrock-2023-05-31",
    max_tokens: 2000,
    temperature: 1,
    messages: [
      {
        role: "user",
        content: [{ type: "text", text: new_chart_prompt }],
      },
    ],
  };

  try {
    // Send the request to Bedrock
    logEvent("chart requested", { results: answer.queryResults.length });

    const command = new InvokeModelCommand({
      contentType: "application/json",
      body: JSON.stringify(payload),
      modelId: CHART_MODEL_ID,
    });

    const apiResponse = await bedrock.send(command);
    const decodedResponseBody = new TextDecoder().decode(apiResponse.body);
    const responseBody = JSON.parse(decodedResponseBody).content[0].text;

    // Process the response
    const has_chart = parseInt(extractBetweenTags(responseBody, "has_chart"));

    if (has_chart) {
      const formatted = applyChartFormatters(
        JSON.parse(extractBetweenTags(responseBody, "chart_configuration"))
      );
      const chart = {
        chart_type: removeCharFromStartAndEnd(
          extractBetweenTags(responseBody, "chart_type"),
          "\n"
        ),
        // Formatters by name only: model output is never evaluated (RB11).
        chart_configuration: formatted.configuration,
        caption: removeCharFromStartAndEnd(
          extractBetweenTags(responseBody, "caption"),
          "\n"
        ),
      };

      logEvent("chart generated", { hasChart: true, droppedFormatters: formatted.dropped });

      return chart;
    } else {
      return {
        rationale: removeCharFromStartAndEnd(
          extractBetweenTags(responseBody, "rationale"),
          "\n"
        ),
      };
    }
  } catch (error) {
    logFailure("chart generation", error);
    return {
      rationale: "Error generating or parsing chart data.",
    };
  }
};
