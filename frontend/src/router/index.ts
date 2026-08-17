import {createRouter, createWebHistory, NavigationGuardNext, RouteLocationNormalized} from 'vue-router';
import NProgress from 'nprogress';
import 'nprogress/nprogress.css';
import {createPinia, storeToRefs} from 'pinia';
import {useKeepALiveNames} from '/@/stores/keepAliveNames';
import {useRoutesList} from '/@/stores/routesList';
import {useThemeConfig} from '/@/stores/themeConfig';
import {Session, Local} from '/@/utils/storage';
import {notFoundAndNoPower, staticRoutes} from '/@/router/route';
import {initFrontEndControlRoutes} from '/@/router/frontEnd';
import {initBackEndControlRoutes} from '/@/router/backEnd';

/**
 * 1、前端控制路由时：isRequestRoutes 为 false，需要写 roles，需要走 setFilterRoute 方法。
 * 2、后端控制路由时：isRequestRoutes 为 true，不需要写 roles，不需要走 setFilterRoute 方法），
 * 相关方法已拆解到对应的 `backEnd.ts` 与 `frontEnd.ts`（他们互不影响，不需要同时改 2 个文件）。
 * 特别说明：
 * 1、前端控制：路由菜单由前端去写（无菜单管理界面，有角色管理界面），角色管理中有 roles 属性，需返回到 userInfo 中。
 * 2、后端控制：路由菜单由后端返回（有菜单管理界面、有角色管理界面）
 */


/**
 * 创建一个可以被 Vue 应用程序使用的路由实例
 * @method createRouter(options: RouterOptions): Router
 * @link 参考：https://next.router.vuejs.org/zh/api/#createrouter
 */
export const router = createRouter({
	history: createWebHistory(),
	/**
	 * 说明：
	 * 1、notFoundAndNoPower 默认添加 404、401 界面，防止一直提示 No match found for location with path 'xxx'
	 * 2、backEnd.ts(后端控制路由)、frontEnd.ts(前端控制路由) 中也需要加 notFoundAndNoPower 404、401 界面。
	 *    防止 404、401 不在 layout 布局中，不设置的话，404、401 界面将全屏显示
	 */
	routes: [...notFoundAndNoPower, ...staticRoutes],
});

/**
 * 路由多级嵌套数组处理成一维数组
 * @param arr 传入路由菜单数据数组
 * @returns 返回处理后的一维路由菜单数组
 */
export function formatFlatteningRoutes(arr: any) {
	if (arr.length <= 0) return false;
	for (let i = 0; i < arr.length; i++) {
		if (arr[i].children) {
			arr = arr.slice(0, i + 1).concat(arr[i].children, arr.slice(i + 1));
		}
	}
	return arr;
}

/**
 * 一维数组处理成多级嵌套数组（只保留二级：也就是二级以上全部处理成只有二级，keep-alive 支持二级缓存）
 * @description isKeepAlive 处理 `name` 值，进行缓存。顶级关闭，全部不缓存
 * @link 参考：https://v3.cn.vuejs.org/api/built-in-components.html#keep-alive
 * @param arr 处理后的一维路由菜单数组
 * @returns 返回将一维数组重新处理成 `定义动态路由（dynamicRoutes）` 的格式
 */
export function formatTwoStageRoutes(arr: any) {
	if (arr.length <= 0) return false;
	const newArr: any = [];
	const cacheList: Array<string> = [];
	arr.forEach((v: any) => {
		if (v.path === '/') {
			newArr.push({
				component: v.component,
				name: v.name,
				path: v.path,
				redirect: v.redirect,
				meta: v.meta,
				children: []
			});
		} else {
			// 确保 meta 存在
			if (!v.meta) v.meta = {};
			// 判断是否是动态路由（xx/:id/:name），用于 tagsView 等中使用
			if (v.path.indexOf('/:') > -1) {
				v.meta['isDynamic'] = true;
				v.meta['isDynamicPath'] = v.path;
			}
			// 安全检查：确保 newArr[0] 已创建（根路由 / 必须先被处理）
			if (newArr.length > 0) {
				newArr[0].children.push({...v});
				// 存 name 值，keep-alive 中 include 使用，实现路由的缓存
				// 路径：/@/layout/routerView/parent.vue
				if (newArr[0].meta?.isKeepAlive && v.meta.isKeepAlive) {
					cacheList.push(v.name);
					const stores = useKeepALiveNames();
					stores.setCacheKeepAlive(cacheList);
				}
			}
		}
	});
	return newArr;
}

// 路由加载前
router.beforeEach(async (to: RouteLocationNormalized, from: RouteLocationNormalized, next: NavigationGuardNext) => {

// 读取 `/src/stores/themeConfig.ts` 是否开启后端控制路由配置
const storesThemeConfig = useThemeConfig();
const {themeConfig} = storeToRefs(storesThemeConfig);
const {isRequestRoutes} = themeConfig.value;

	NProgress.configure({showSpinner: false});
	if (to.meta.title) NProgress.start();
	const token = Local.get('token');
	// OAuth 回调路由不需要 token 验证
	if (to.path.startsWith('/oauth/') && to.path.includes('/callback')) {
		next();
		NProgress.done();
	} else if (to.path === '/login' && !token) {
		next();
		NProgress.done();
	} else {
		if (!token) {
			next('/login');
			Session.clear();
			NProgress.done();
		} else if (token && to.path === '/login') {
			next('/home');
			NProgress.done();
		} else {
			const storesRoutesList = useRoutesList();
			const {routesList, isGet} = storeToRefs(storesRoutesList);
			if (routesList.value.length === 0 && !isGet.value) {
				if (isRequestRoutes) {
					// 后端控制路由：路由数据初始化，防止刷新时丢失
					try {
						await initBackEndControlRoutes();
						// 确保路由初始化完成后再进行导航
						// 使用 nextTick 确保 DOM 更新完成
						await new Promise(resolve => setTimeout(resolve, 100));
						// 检查目标路由是否已注册
						const targetRoute = router.resolve(to.path);
						if (targetRoute.matched.length > 0) {
							next({path: to.path, query: to.query});
						} else {
							// 如果路由仍未找到，尝试导航到首页
							console.warn(`路由未找到: ${to.path}，重定向到首页`);
							next('/home');
						}
					} catch (error) {
						console.error('路由初始化失败:', error);
						next('/home');
					}
				} else {
					try {
						await initFrontEndControlRoutes();
						await new Promise(resolve => setTimeout(resolve, 100));
						const targetRoute = router.resolve(to.path);
						if (targetRoute.matched.length > 0) {
							next({path: to.path, query: to.query});
						} else {
							next('/home');
						}
					} catch (error) {
						console.error('前端路由初始化失败:', error);
						next('/home');
					}
				}
			} else {
				next();
			}
		}
	}
});

// 路由加载后
router.afterEach(() => {
	NProgress.done();
});

// 导出路由
export default router;
