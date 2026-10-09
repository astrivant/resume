// Apply browser globals and concise correctness/style rules to Selenium page scripts only.
export default [
  {
    files: ['pkg/resumeme/linkedin/scripts/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      parserOptions: {
        ecmaFeatures: { globalReturn: true },
      },
      globals: {
        Node: 'readonly',
        arguments: 'readonly',
        document: 'readonly',
        getComputedStyle: 'readonly',
      },
    },
    rules: {
      curly: 'error',
      eqeqeq: ['error', 'always'],
      indent: ['error', 2],
      'no-constant-condition': 'error',
      'no-dupe-keys': 'error',
      'no-undef': 'error',
      'no-unreachable': 'error',
      'no-unused-vars': ['error', { args: 'none' }],
      'no-var': 'error',
      'prefer-const': 'error',
      quotes: ['error', 'single', { avoidEscape: true }],
      semi: ['error', 'always'],
    },
  },
];
