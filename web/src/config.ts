// Settings from web/.env.local (see .env.example). Vite puts VITE_* values into the built files.
import { Amplify } from "aws-amplify";

export const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const userPoolId = import.meta.env.VITE_USER_POOL_ID ?? "";
const userPoolClientId = import.meta.env.VITE_USER_POOL_CLIENT_ID ?? "";

export const missingConfig = [
  ["VITE_API_URL", API_URL],
  ["VITE_USER_POOL_ID", userPoolId],
  ["VITE_USER_POOL_CLIENT_ID", userPoolClientId],
]
  .filter(([, value]) => !value)
  .map(([name]) => name);

// Only Amplify's Auth part is used: it talks to Cognito (sign-up, sign-in, tokens).
// Tokens are kept in the browser's localStorage and refreshed automatically.
export function configureAmplify() {
  if (missingConfig.length) return;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: { email: true },
        signUpVerificationMethod: "code",
      },
    },
  });
}
