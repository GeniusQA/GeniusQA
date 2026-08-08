import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';
import { defineConfig, loadEnv, ConfigEnv } from 'vite';
import vueSetupExtend from 'vite-plugin-vue-setup-extend';
import monacoEditorPlugin from 'vite-plugin-monaco-editor';

const pathResolve = (dir: string) => {
	return resolve(__dirname, '.', dir);
};

const alias: Record<string, string> = {
	'/@': pathResolve('./src/'),
	'@': pathResolve('./src/'),
};

const viteConfig = defineConfig((mode: ConfigEnv) => {
	const env = loadEnv(mode.mode, process.cwd());
	return {
		plugins: [
			vue(),
			vueSetupExtend(),
			// Vite 8：插件入参不可省略，否则读取 languageWorkers 会报错
			monacoEditorPlugin({
				languageWorkers: ['editorWorkerService', 'css', 'html', 'json', 'typescript'],
			}),
		],
		optimizeDeps: {
			include: [
				'vue',
				'vue-router',
				'@vueuse/core',
				'pinia',
				'axios',
				'splitpanes',
				'screenfull',
				'echarts',
				'monaco-editor',
				'element-plus/es',
				'element-plus/es/components/form/style/index',
				'element-plus/es/components/radio-group/style/index',
				'element-plus/es/components/radio/style/index',
				'element-plus/es/components/checkbox/style/index',
				'element-plus/es/components/checkbox-group/style/index',
				'element-plus/es/components/switch/style/index',
				'element-plus/es/components/time-picker/style/index',
				'element-plus/es/components/date-picker/style/index',
				'element-plus/es/components/col/style/index',
				'element-plus/es/components/form-item/style/index',
				'element-plus/es/components/alert/style/index',
				'element-plus/es/components/breadcrumb/style/index',
				'element-plus/es/components/select/style/index',
				'element-plus/es/components/input/style/index',
				'element-plus/es/components/breadcrumb-item/style/index',
				'element-plus/es/components/tag/style/index',
				'element-plus/es/components/pagination/style/index',
				'element-plus/es/components/table/style/index',
				'element-plus/es/components/table-column/style/index',
				'element-plus/es/components/card/style/index',
				'element-plus/es/components/row/style/index',
				'element-plus/es/components/button/style/index',
				'element-plus/es/components/menu/style/index',
				'element-plus/es/components/sub-menu/style/index',
				'element-plus/es/components/menu-item/style/index',
				'element-plus/es/components/option/style/index',
				'@element-plus/icons-vue',
			],
		},
		root: process.cwd(),
		cacheDir: require('os').tmpdir() + '/vite-cache',
		resolve: { alias },
		base: mode.command === 'serve' ? './' : env.VITE_PUBLIC_PATH,
		server: {
			host: '0.0.0.0',
			port: env.VITE_PORT as unknown as number,
			open: env.VITE_OPEN?.toLowerCase() === 'true',
			hmr: true,
			allowedHosts: ['genius.tail83d0a7.ts.net'],
			proxy: {
				// API 文档与 OpenAPI 直通到后端，避免被前端 SPA 路由拦截
				'/docs': {
					target: 'http://127.0.0.1:8100',
					changeOrigin: true,
					secure: false,
				},
				'/redoc': {
					target: 'http://127.0.0.1:8100',
					changeOrigin: true,
					secure: false,
				},
				'/openapi.json': {
					target: 'http://127.0.0.1:8100',
					changeOrigin: true,
					secure: false,
				},
				// Swagger UI 静态资源（CSS/JS）
				'/static': {
					target: 'http://127.0.0.1:8100',
					changeOrigin: true,
					secure: false,
				},
				// 所有 /api 请求也代理到后端
				'/api': {
					target: 'http://127.0.0.1:8100',
					changeOrigin: true,
					secure: false,
				},
			},
		},
		build: {
			outDir: 'dist',
			emptyOutDir: false,
			chunkSizeWarningLimit: 1500,
			// Lightning CSS 对历史写法更严格
			cssMinify: 'esbuild',
			// Vite 8 / Rolldown：rollupOptions → rolldownOptions，manualChunks → codeSplitting
			rolldownOptions: {
				output: {
					entryFileNames: `assets/[name].[hash].js`,
					chunkFileNames: `assets/[name].[hash].js`,
					assetFileNames: `assets/[name].[hash].[ext]`,
					codeSplitting: {
						groups: [
							{
								name: 'vue',
								test: /[\\/]node_modules[\\/](vue|vue-router|pinia)([\\/]|$)/,
							},
							{
								name: 'echarts',
								test: /[\\/]node_modules[\\/]echarts([\\/]|$)/,
							},
						],
					},
				},
			},
		},
		css: {
			preprocessorOptions: {
				css: { charset: false },
				scss: {
					silenceDeprecations: ['legacy-js-api', 'import'],
					quietDeps: true,
					charset: false,
					additionalData: `
            // 全局变量可以在这里定义
            // $primary-color:rgb(243, 75, 9);
          `,
				},
			},
			postcss: {
				plugins: [
					{
						postcssPlugin: 'internal:charset-removal',
						AtRule: {
							charset: (atRule) => {
								if (atRule.name === 'charset') {
									atRule.remove();
								}
							},
						},
					},
				],
			},
		},
		define: {
			__VERSION__: JSON.stringify(process.env.npm_package_version),
		},
	};
});

export default viteConfig;
