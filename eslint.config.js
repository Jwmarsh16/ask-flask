// eslint.config.js
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
// ✅ ADDED: Testing plugins for RTL + jest-dom rules
import testingLibrary from 'eslint-plugin-testing-library' // add testing-library rules
import jestDom from 'eslint-plugin-jest-dom'               // add jest-dom rules

export default [
  { ignores: ['dist', 'coverage'] }, // ✅ ADDED: ignore coverage output
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  },
  // ✅ ADDED: Test-specific overrides (Vitest/RTL + jest-dom)
  {
    files: [
      '**/__tests__/**/*.{js,jsx}', // match our test files
      'client/src/test/**/*.{js,jsx}',
    ],
    languageOptions: {
      // Provide Vitest globals so ESLint doesn't flag them as undefined
      globals: {
        ...globals.browser,
        ...globals.node,
        vi: 'readonly',
        describe: 'readonly',
        it: 'readonly',
        test: 'readonly',
        expect: 'readonly',
        beforeEach: 'readonly',
        afterEach: 'readonly',
      },
    },
    plugins: {
      'testing-library': testingLibrary, // enable plugin
      'jest-dom': jestDom,               // enable plugin
    },
    // Pull in the plugins' recommended rule sets (flat-config aware)
    rules: {
      ...(testingLibrary.configs['flat/recommended']?.rules ?? {}), // ✅ apply RTL best-practices
      ...(jestDom.configs['flat/recommended']?.rules ?? {}),        // ✅ apply jest-dom best-practices
    },
  },
]
