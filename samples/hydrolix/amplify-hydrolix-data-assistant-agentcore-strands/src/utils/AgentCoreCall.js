import { v4 as uuidv4 } from "uuid";
import { getAccessToken } from "./AwsAuth";
import { logEvent, logFailure } from "./logMetadata";
import { createSseParser } from "./sseRecords";
import { getQueryResults } from "./AwsCalls";
import { AGENT_RUNTIME_ARN, AGENT_ENDPOINT_NAME } from "../env";

export const getAnswer = async (
  my_query,
  sessionId,
  setControlAnswers,
  setAnswers,
  setEnabled,
  setLoading,
  setErrorMessage,
  setQuery,
  setCurrentWorkingToolId
) => {
  if (!setLoading || my_query === "") return;

  setControlAnswers((prevState) => [...prevState, {}]);
  setAnswers((prevState) => [...prevState, { query: my_query }]);
  setEnabled(false);
  setLoading(true);
  setErrorMessage("");
  setQuery("");

  try {
    const queryUuid = uuidv4();
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    let json = {
      text: [],
      queryUuid,
    };


    // Add initial answer object to state
    setControlAnswers((prevState) => [
      ...prevState,
      { current_tab_view: "answer" },
    ]);
    setAnswers((prevState) => [...prevState, json]);

    // The runtime takes the user from the verified access token's `sub` and the
    // conversation from the runtime session header, never from the payload.
    const payload = JSON.stringify({
      prompt: my_query,
      prompt_uuid: queryUuid,
      user_timezone: timezone,
      last_k_turns: 10,
    });

    // InvokeAgentRuntime over HTTPS with the Cognito access token (OAuth, not SigV4).
    const region = AGENT_RUNTIME_ARN.split(":")[3];
    const invokeUrl =
      `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/` +
      `${encodeURIComponent(AGENT_RUNTIME_ARN)}/invocations` +
      `?qualifier=${encodeURIComponent(AGENT_ENDPOINT_NAME)}`;
    const httpResponse = await fetch(invokeUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${await getAccessToken()}`,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
      },
      body: payload,
    });
    if (!httpResponse.ok) {
      throw new Error(
        `The assistant refused the request (HTTP ${httpResponse.status}). Sign in again and retry.`
      );
    }
    const response = { response: httpResponse.body };

    let responseText = "";
    let currentTextItem = "";
    let textArray = [];

    const BEDROCK_UNAVAILABLE = [
      "serviceUnavailableException",
      "Bedrock is unable to process your request",
      "I apologize, but I encountered an error",
    ];
    const unavailable = () =>
      new Error("Bedrock service is currently unavailable. Please try again in a few moments.");
    let records = 0;
    let unknownEvents = 0;
    let currentToolName = "";

    // One record's text (what the runtime yielded) into the answer being built.
    const handleText = (text) => {
      records += 1;
      if (BEDROCK_UNAVAILABLE.some((marker) => text.includes(marker))) {
        throw unavailable();
      }
      let jsonData;
      try {
        jsonData = JSON.parse(text);
      } catch (error) {
        logFailure("parse runtime record", error);
        return;
      }
      if (jsonData.error) {
        throw new Error(jsonData.error);
      }
      if (jsonData.event?.contentBlockStart?.start?.toolUse) {
        // Add accumulated text before tool block
        if (currentTextItem.trim()) {
          textArray.push({ type: "text", content: currentTextItem });
          currentTextItem = "";
        }
        const toolUse = jsonData.event.contentBlockStart.start.toolUse;
        currentToolName = toolUse.name;
        setCurrentWorkingToolId(toolUse.toolUseId);
        textArray.push({
          type: "tool",
          toolUseId: toolUse.toolUseId,
          name: toolUse.name,
          inputs: "",
        });
      } else if (jsonData.toolUseId && jsonData.name) {
        // Tool use input update
        const lastItem = textArray[textArray.length - 1];
        if (lastItem && lastItem.type === "tool" && lastItem.toolUseId === jsonData.toolUseId) {
          try {
            lastItem.inputs = JSON.parse(jsonData.input);
          } catch (error) {
            logFailure("parse tool input", error); // inputs stream in; the last one parses
          }
          setCurrentWorkingToolId(jsonData.toolUseId);
        }
      } else if (jsonData.event?.contentBlockStop) {
        // Content block ended
      } else if (jsonData.start_event_loop) {
        currentToolName = "";
      } else if (typeof jsonData.data === "string") {
        if (BEDROCK_UNAVAILABLE.some((marker) => jsonData.data.includes(marker))) {
          throw unavailable();
        }
        currentToolName = "";
        currentTextItem += jsonData.data;
        responseText += jsonData.data;
        setCurrentWorkingToolId(null);
      } else if (!jsonData.notice) {
        unknownEvents += 1;
      }
    };

    const showProgress = () =>
      setAnswers((prev) => {
        const newAnswers = [...prev];
        const lastIndex = newAnswers.length - 1;
        const currentArray = [...textArray];
        if (currentTextItem.trim()) {
          currentArray.push({ type: "text", content: currentTextItem });
        }
        newAnswers[lastIndex] = { ...newAnswers[lastIndex], text: currentArray, currentToolName };
        return newAnswers;
      });

    try {
      const reader = response.response.getReader();
      // Records can be split across reads (and mid-character): the parser buffers them.
      const parser = createSseParser();
      try {
        while (true) {
          const { done, value } = await reader.read();
          const texts = done ? parser.end() : parser.push(value);
          texts.forEach(handleText);
          showProgress();
          if (done) break;
        }
      } finally {
        reader.releaseLock();
      }
    } catch (streamError) {
      logFailure("read runtime stream", streamError);
      throw streamError;
    }
    logEvent("runtime stream ended", {
      records,
      unknownEvents,
      answerLength: responseText.length,
    });

    // Final update with complete text
    setAnswers((prev) => {
      const newAnswers = [...prev];
      const lastIndex = newAnswers.length - 1;
      const finalArray = [...textArray];

      // Add any remaining text that wasn't added during streaming
      if (currentTextItem.trim()) {
        finalArray.push({ type: "text", content: currentTextItem });
      }

      newAnswers[lastIndex] = {
        ...newAnswers[lastIndex],
        text: finalArray,
        queryUuid,
      };
      return newAnswers;
    });

    // After streaming is complete, fetch query results for charts/tables
    try {
      const queryResults = await getQueryResults(queryUuid);
      logEvent("query results loaded", { results: queryResults.length });

      if (queryResults.length > 0) {
        // Update the answer with query results
        setAnswers((prev) => {
          const newAnswers = [...prev];
          const lastIndex = newAnswers.length - 1;
          newAnswers[lastIndex] = {
            ...newAnswers[lastIndex],
            queryResults: queryResults,
            chart: "loading", // Indicate chart generation is starting
          };
          return newAnswers;
        });
      }
    } catch (queryError) {
      logFailure("load query results", queryError);
    }

    setLoading(false);
    setEnabled(false);
    // Clear current working tool when processing is complete
    setCurrentWorkingToolId(null);

  } catch (error) {
    logFailure("ask the assistant", error);
    if (error.message.includes("Bedrock service is currently unavailable")) {
      setErrorMessage(
        "🚨 Bedrock AI service is temporarily unavailable. Please try again in a few moments."
      );
    } else if (error.message.includes("ERR_HTTP2_PROTOCOL_ERROR")) {
      setErrorMessage(
        "Connection protocol error. Response may be complete despite the error."
      );
    } else if (error.message.includes("ERR_INCOMPLETE_CHUNKED_ENCODING")) {
      setErrorMessage(
        "Connection interrupted. Partial response may be available."
      );
    } else {
      setErrorMessage(error.toString());
    }
    setLoading(false);
    setEnabled(false);
    // Clear current working tool on error
    setCurrentWorkingToolId(null);

    // Update the streaming answer with error state
    setAnswers((prevState) => {
      const newState = [...prevState];
      for (let i = newState.length - 1; i >= 0; i--) {
        if (newState[i].text && Array.isArray(newState[i].text)) {
          newState[i] = {
            ...newState[i],
            text: [{ type: "text", content: "Error occurred while getting response" }],
            error: true,
          };
          break;
        }
      }
      return newState;
    });
  }
};