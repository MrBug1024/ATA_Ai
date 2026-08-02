import { loadEnvFile } from "process";
import { resolve } from "path";

// Load test environment variables
loadEnvFile(resolve(__dirname, ".env.test"));
