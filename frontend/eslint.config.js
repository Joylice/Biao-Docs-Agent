import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'dist-verify*/**',
      'node_modules/**',
      'vite.config.js',
      'vite.config.d.ts',
      '**/*.tsbuildinfo',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    // scripts/ 下是 Node 脚本（如契约守卫 check-editor-contracts.mjs），
    // 需要 Node 全局；否则 no-undef 会报 'process' is not defined。
    files: ['scripts/**/*.mjs'],
    languageOptions: {
      globals: { process: 'readonly' },
    },
  },
  {
    rules: {
      // 下划线前缀参数/变量为「故意不用」的占位约定（如预留扩展的入参）
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
    },
  },
)
