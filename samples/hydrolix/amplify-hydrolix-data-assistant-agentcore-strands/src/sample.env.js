// ================================
// CUSTOMIZABLE CONFIGURATION VALUES
// ================================

// Amazon Bedrock AgentCore Configuration
const AGENT_RUNTIME_ARN = "";
const AGENT_ENDPOINT_NAME = "DEFAULT";
const LAST_K_TURNS = 10; // AgentCore Memory - Retrieve the last K conversation turns for context memory

// Application Information - CUSTOMIZE AS NEEDED
const APP_NAME = "Hydrolix CDN Insights";
const APP_SUBJECT = "Real-Time Streaming Analytics";
const WELCOME_MESSAGE = "I'm Gus, your Hydrolix CDN analytics expert. Ask me about cache performance, viewer experience, streaming quality, or any insights from your data.";

// ================================
// SYSTEM CONFIGURATION
// ================================

const MAX_LENGTH_INPUT_SEARCH = 140;
const CHART_MODEL_ID = process.env.REACT_APP_CHART_MODEL_ID;


export {
  // Amazon Bedrock AgentCore
  AGENT_RUNTIME_ARN,
  AGENT_ENDPOINT_NAME,
  LAST_K_TURNS,
  
  // Application Information
  APP_NAME,
  APP_SUBJECT,
  WELCOME_MESSAGE,
  
  // System Configuration
  MAX_LENGTH_INPUT_SEARCH,
  CHART_MODEL_ID,
};
