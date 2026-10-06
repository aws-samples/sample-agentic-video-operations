import { fetchAuthSession } from "aws-amplify/auth";
import { logFailure } from "./logMetadata";
import { fromCognitoIdentityPool } from "@aws-sdk/credential-providers";
import config from "../amplifyconfiguration.json";

/**
 * The signed-in user's Cognito access token. The assistant runtime accepts only this token
 * (inbound JWT authorization) and takes the user's identity from its `sub`.
 * @returns {Promise<string>} The access token
 */
export const getAccessToken = async () => {
  const session = await fetchAuthSession();
  const accessToken = session.tokens?.accessToken?.toString();
  if (!accessToken) {
    throw new Error("Authentication token not available. Please sign in again.");
  }
  return accessToken;
};

/**
 * Creates AWS configuration with authenticated credentials
 * @returns {Promise<Object>} AWS configuration object with credentials
 */
export const getAwsCredentials = async () => {
  try {
    // Get authentication token from Cognito
    const session = await fetchAuthSession();
    const authToken = session.tokens?.idToken?.toString();
    
    if (!authToken) {
      throw new Error("Authentication token not available. Please sign in again.");
    }
    
    // Create the login map for the Cognito Identity Pool
    const loginProvider = `cognito-idp.${config.aws_project_region}.amazonaws.com/${config.aws_user_pools_id}`;
    const logins = { [loginProvider]: authToken };
    
    // Create credentials provider
    const credentials = fromCognitoIdentityPool({
      clientConfig: { region: config.aws_project_region },
      identityPoolId: config.aws_cognito_identity_pool_id,
      logins: logins
    });
    
    return credentials;
  } catch (error) {
    logFailure("get AWS credentials", error);
    throw new Error("Authentication failed. Please try signing in again.");
  }
};

/**
 * Creates AWS service client configuration
 * @param {Object} options - Additional configuration options
 * @returns {Promise<Object>} Configuration for AWS service clients
 */
export const getAwsConfig = async (options = {}) => {
  const credentials = await getAwsCredentials();
  
  return {
    region: config.aws_project_region,
    credentials,
    ...options
  };
};

/**
 * Creates client for a specific AWS service with authenticated credentials
 * @param {Function} ClientConstructor - AWS SDK client constructor
 * @param {Object} options - Additional client options
 * @returns {Promise<Object>} Configured AWS service client
 */
export const createAwsClient = async (ClientConstructor, options = {}) => {
  const clientConfig = await getAwsConfig(options);
  return new ClientConstructor(clientConfig);
};