// client/eslint.config.js
// CHANGED: add client-local flat config so CI resolves deps from client/node_modules (avoids loading repo-root eslint.config.js)

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
// CHANGED: testing plugins for RTL + jest-dom rules
import testingLibrary from "eslint-plugin-testing-library";
import jestDom from "eslint-plugin-jest-dom";

export default [
  { ignores: ["dist", "coverage"] }, // CHANGED: ignore build + test output inside client/
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: "latest",
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "no-unused-vars": [
        "error",
        {
          varsIgnorePattern: "^[A-Z_]",
          args: "after-used", // CHANGED: keep strictness, but allow intentional unused args
          argsIgnorePattern: "^_", // CHANGED: allow unused args like `_err`
          caughtErrors: "all", // CHANGED: apply caughtErrorsIgnorePattern consistently
          caughtErrorsIgnorePattern: "^_", // CHANGED: allow unused catch params like `catch (_e)`
        },
      ],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  // CHANGED: test-specific overrides (Vitest/RTL + jest-dom)
  {
    files: [
      "**/__tests__/**/*.{js,jsx}", // CHANGED: match test files under client/
      "src/test/**/*.{js,jsx}", // CHANGED: client-relative path (CI runs lint from client/)
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        vi: "readonly",
        describe: "readonly",
        it: "readonly",
        test: "readonly",
        expect: "readonly",
        beforeEach: "readonly",
        afterEach: "readonly",
      },
    },
    plugins: {
      "testing-library": testingLibrary,
      "jest-dom": jestDom,
    },
    rules: {
      ...(testingLibrary.configs["flat/recommended"]?.rules ?? {}),
      ...(jestDom.configs["flat/recommended"]?.rules ?? {}),
    },
  },
];
