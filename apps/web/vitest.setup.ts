import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// We run Vitest without `globals`, so RTL's auto-cleanup afterEach isn't registered — wire it
// explicitly so each test starts with a clean DOM (otherwise renders accumulate across tests).
afterEach(cleanup);
