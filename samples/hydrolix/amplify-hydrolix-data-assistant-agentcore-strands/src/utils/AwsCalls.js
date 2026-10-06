import { DynamoDBClient, QueryCommand } from "@aws-sdk/client-dynamodb";
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
import { QUESTION_ANSWERS_TABLE_NAME, CHART_MODEL_ID } from "../env.js";
import { CHART_PROMPT } from "../prompts/chartPrompt.js";

/**
 * Query data from DynamoDB
 *
 * @param {string} id - The ID to query
 * @returns {Promise<Object>} - The query response
 */
export const getQueryResults = async (queryUuid = "") => {
  let queryResults = [];
  try {
    const dynamodb = await createAwsClient(DynamoDBClient);
    const input = {
      TableName: QUESTION_ANSWERS_TABLE_NAME,
      KeyConditionExpression: "id = :queryUuid",
      ExpressionAttributeValues: {
        ":queryUuid": {
          S: queryUuid,
        },
      },
      ConsistentRead: true,
    };
    const command = new QueryCommand(input);
    const response = await dynamodb.send(command);
    if (response.hasOwnProperty("Items")) {
      for (let i = 0; i < response.Items.length; i++) {
        const parsedData = JSON.parse(response.Items[i].data.S);
        queryResults.push({
          query: response.Items[i].sql_query.S,
          query_results: parsedData.result || [],
          query_description: response.Items[i].sql_query_description.S,
          agent_name: response.Items[i].agent_name?.S || "",
          user_prompt: response.Items[i].user_prompt?.S || "",
          my_timestamp: parseInt(response.Items[i].my_timestamp?.N || "0", 10),
        });
      }

      // Sort ascending by timestamp
      queryResults.sort((a, b) => a.my_timestamp - b.my_timestamp);

      // Group by agent_name while preserving order
      const grouped = [];
      const agentMap = {};
      for (const qr of queryResults) {
        const key = qr.agent_name;
        if (!agentMap[key]) {
          agentMap[key] = [];
          grouped.push(key);
        }
        agentMap[key].push(qr);
      }
      queryResults = grouped.flatMap((key) => agentMap[key]);
    }
    return queryResults;
  } catch (error) {
    logFailure("query results table", error);
    throw error;
  }
};

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
