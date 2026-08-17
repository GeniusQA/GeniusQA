import {RouteRecordRaw} from 'vue-router';
import {useUserStore} from '/@/stores/user';
import {useRequestOldRoutes} from '/@/stores/requestOldRoutes';
import {Session} from '/@/utils/storage';
import {NextLoading} from '/@/utils/loading';
import {dynamicRoutes, notFoundAndNoPower} from '/@/router/route';
import {formatFlatteningRoutes, formatTwoStageRoutes, router} from '/@/router';
import {useRoutesList} from '/@/stores/routesList';
import {useTagsViewRoutes} from '/@/stores/tagsViewRoutes';
import {useUserApi} from '/@/api/v1/system/user';
import {useLookupStore} from "/@/stores/lookup";
import {useMenuInfo} from "/@/stores/menu";


/**
 * 获取目录下的 .vue、.tsx 全部文件
 * @method import.meta.glob
 * @link 参考：https://cn.vitejs.dev/guide/features.html#json
 */
const layoutModules: any = import.meta.glob('../layout/routerView/*.{vue,tsx}');
const viewsModules: any = import.meta.glob('../views/**/*.{vue,tsx}');
const dynamicViewsModules = Object.assign({}, {...layoutModules}, {...viewsModules});

/**
 * 后端控制路由：初始化方法，防止刷新时路由丢失
 * @method NextLoading 界面 loading 动画开始执行
 * @method useUserStore().setUserInfos() 触发初始化用户信息 pinia
 * @method useRequestOldRoutes().setRequestOldRoutes() 存储接口原始路由（未处理component），根据需求选择使用
 * @method setAddRoute 添加动态路由
 * @method setFilterMenuAndCacheTagsViewRoutes 设置路由到 pinia routesList 中（已处理成多级嵌套路由）及缓存多级嵌套数组处理后的一维数组
 */
export async function initBackEndControlRoutes() {
	// 界面 loading 动画开始执行
	if (window.nextLoading === undefined) NextLoading.start();
	// 无 token 停止执行下一步
	if (!Local.get('token')) return false;
	
	try {
		// 触发初始化用户信息 pinia
		await useUserStore().setUserInfos();
		// 设置数据字典
		await useLookupStore().setLookup();
		// 获取路由菜单数据
		const menuData = await useMenuInfo().getMenuData();
		
		// 验证菜单数据
		if (!menuData || !Array.isArray(menuData) || menuData.length === 0) {
			console.warn('菜单数据为空或格式错误');
			return false;
		}
		
		// 存储接口原始路由（未处理component），根据需求选择使用
		await useRequestOldRoutes().setRequestOldRoutes(JSON.parse(JSON.stringify(menuData)));
		
	// 保留静态隐藏路由（isHide: true 且无需后端配置的页面，如工作流编辑器、报告页、external-agent 等）
	// 注意：必须递归收集所有层级下的隐藏路由，不能只看根 children
	const staticHiddenRoutes: RouteRecordRaw[] = [];
	const collectHiddenRoutes = (routes: any[]) => {
		for (const r of routes || []) {
			if (r.meta?.isHide === true) {
				staticHiddenRoutes.push(r);
			}
			if (r.children?.length) {
				collectHiddenRoutes(r.children);
			}
		}
	};
	collectHiddenRoutes(dynamicRoutes[0].children as RouteRecordRaw[]);

		// 清空动态路由的children，避免与静态路由冲突
		dynamicRoutes[0].children = [];
		
		// 处理路由（component），替换 dynamicRoutes（/@/router/route）第一个顶级 children 的路由
		const processedRoutes = await backEndComponent(menuData);
		if (processedRoutes && processedRoutes.length > 0) {
			dynamicRoutes[0].children = processedRoutes;
		}

		// 将静态隐藏路由合并回去（去重，避免后端也返回了同名路由）
		for (const staticRoute of staticHiddenRoutes) {
			const alreadyExists = (dynamicRoutes[0].children as RouteRecordRaw[]).some(
				(r: any) => r.name === staticRoute.name || r.path === staticRoute.path
			);
			if (!alreadyExists) {
				(dynamicRoutes[0].children as RouteRecordRaw[]).push(staticRoute);
			}
		}
		
		// 添加动态路由
		await setAddRoute();
		
		// 设置路由到 pinia routesList 中（已处理成多级嵌套路由）及缓存多级嵌套数组处理后的一维数组
		await setFilterMenuAndCacheTagsViewRoutes();
		
		// 验证APP路由是否正确注册
		const allRoutes = router.getRoutes();
		const appRoutes = allRoutes.filter(r => 
			r.path.includes('/app_manage') || r.path.includes('/app_report')
		);
		
		if (appRoutes.length > 0) {
			console.log(`✅ 成功注册 ${appRoutes.length} 个APP路由`);
		} else {
			console.warn('⚠️ 未找到APP相关路由');
		}
		
		return true;
	} catch (error) {
		console.error('路由初始化失败:', error);
		return false;
	}
}

/**
 * 设置路由到 pinia routesList 中（已处理成多级嵌套路由）及缓存多级嵌套数组处理后的一维数组
 * @description 用于左侧菜单、横向菜单的显示
 * @description 用于 tagsView、菜单搜索中：未过滤隐藏的(isHide)
 */
export async function setFilterMenuAndCacheTagsViewRoutes() {
	const storesRoutesList = useRoutesList();
	await storesRoutesList.setRoutesList(dynamicRoutes[0].children as any);
	await storesRoutesList.setIsGet(true);
	setCacheTagsViewRoutes();
}

/**
 * 缓存多级嵌套数组处理后的一维数组
 * @description 用于 tagsView、菜单搜索中：未过滤隐藏的(isHide)
 */
export function setCacheTagsViewRoutes() {
	const storesTagsView = useTagsViewRoutes();
	storesTagsView.setTagsViewRoutes(formatTwoStageRoutes(formatFlatteningRoutes(dynamicRoutes))[0].children);
}

/**
 * 处理路由格式及添加捕获所有路由或 404 Not found 路由
 * @description 替换 dynamicRoutes（/@/router/route）第一个顶级 children 的路由
 * @returns 返回替换后的路由数组
 */
export function setFilterRouteEnd() {
	let filterRouteEnd = formatTwoStageRoutes(formatFlatteningRoutes(dynamicRoutes));
	// notFoundAndNoPower 防止 404、401 不在 layout 布局中，不设置的话，404、401 界面将全屏显示
	// 关联问题 No match found for location with path 'xxx'
	filterRouteEnd[0].children = [...filterRouteEnd[0].children, ...notFoundAndNoPower];
	return filterRouteEnd;
}

/**
 * 添加动态路由
 * @method router.addRoute
 * @description 此处循环为 dynamicRoutes（/@/router/route）第一个顶级 children 的路由一维数组，非多级嵌套
 * @link 参考：https://next.router.vuejs.org/zh/api/#addroute
 */
export async function setAddRoute() {
	const routes = setFilterRouteEnd();
	
	if (!routes || routes.length === 0) {
		console.warn('没有路由需要添加');
		return;
	}
	
	let successCount = 0;
	let failCount = 0;
	
	// 添加路由
	routes.forEach((route: RouteRecordRaw) => {
		try {
			// 检查路由是否已存在
			const existingRoute = router.hasRoute(route.name as string);
			if (existingRoute) {
				router.removeRoute(route.name as string);
			}
			
			router.addRoute(route);
			successCount++;
			
			// 特别检查APP相关路由
			if (route.path?.includes('/app_manage') || route.path?.includes('/app_report')) {
				console.log(`✅ [APP路由] 成功注册: ${route.path} -> ${route.name}`);
			}
		} catch (error) {
			console.error(`❌ [Router] 添加路由失败: ${route.name} -> ${route.path}`, error);
			failCount++;
		}
	});
	
	console.log(`路由注册完成: 成功 ${successCount} 个，失败 ${failCount} 个`);
	
	// 等待路由注册完成
	await new Promise(resolve => setTimeout(resolve, 50));
}

/**
 * 请求后端路由菜单接口
 * @description isRequestRoutes 为 true，则开启后端控制路由
 * @returns 返回后端路由菜单数据
 */
export async function getBackEndControlRoutes() {
	let {data} = await useUserApi().getMenuByToken()
	return data
}

/**
 * 重新请求后端路由菜单接口
 * @description 用于菜单管理界面刷新菜单（未进行测试）
 * @description 路径：/src/views/system/menu/component/addMenu.vue
 */
export async function setBackEndControlRefreshRoutes() {
	await getBackEndControlRoutes();
}

/**
 * 后端路由 component 转换
 * @param routes 后端返回的路由表数组
 * @returns 返回处理成函数后的 component
 */
export function backEndComponent(routes: any) {
	if (!routes) return;
	
	// 用于跟踪已使用的路由名称
	const usedNames = new Set<string>();
	
	const processRoute = (item: any, parentPath = '', level = 0) => {
		if (item.component) {
			item.component = dynamicImport(dynamicViewsModules, item.component);
		}
		
		// 生成唯一的路由名称
		if (item.path) {
			// 使用菜单ID作为路由名称，确保唯一性
			let routeName = `menu-${item.id || Math.random().toString(36).substr(2, 9)}`;
			
			// 如果没有ID，从路径生成
			if (!item.id) {
				routeName = item.path
					.replace(/^\//, '') // 移除开头的斜杠
					.replace(/\//g, '-') // 将斜杠替换为连字符
					.replace(/[^a-zA-Z0-9-]/g, '') // 移除特殊字符
					.toLowerCase();
				
				if (!routeName) {
					routeName = `route-${level}-${Math.random().toString(36).substr(2, 9)}`;
				}
			}
			
			// 确保名称唯一
			let uniqueName = routeName;
			let counter = 1;
			while (usedNames.has(uniqueName)) {
				uniqueName = `${routeName}-${counter}`;
				counter++;
			}
			
			item.name = uniqueName;
			usedNames.add(uniqueName);
			
			// 只为APP相关路由输出日志
			if (item.path?.includes('/app_manage') || item.path?.includes('/app_report')) {
				console.log(`🏷️ [APP路由] 生成路由名称: ${item.path} -> ${uniqueName} (ID: ${item.id})`);
			}
		}
		
		// 递归处理子路由
		if (item.children && Array.isArray(item.children)) {
			item.children.forEach((child: any) => processRoute(child, item.path, level + 1));
		}
		
		
        // Ensure every route has a meta object (prevent "Cannot read properties of undefined (reading 'meta')")
        if (!item.meta) item.meta = {};
        return item;
	};
	
	return routes.map((item: any) => processRoute(item));
}

/**
 * 后端路由 component 转换函数
 * @param dynamicViewsModules 获取目录下的 .vue、.tsx 全部文件
 * @param component 当前要处理项 component
 * @returns 返回处理成函数后的 component
 */
export function dynamicImport(dynamicViewsModules: Record<string, Function>, component: string) {
	const keys = Object.keys(dynamicViewsModules);
	
	// 标准化组件路径
	const normalizedComponent = component.replace(/^\//, '').replace(/\.vue$/, '');
	
	const matchKeys = keys.filter((key) => {
		// 处理路径：移除 ../views 或 ../layout 前缀，保留相对模块路径
		const k = key
			.replace(/^\.\.\/views\//, '')
			.replace(/^\.\.\/layout\//, 'layout/')
			.replace(/\.vue$/, '')
			.replace(/\.tsx$/, '');
		
		// 多种匹配策略
		const match1 = k === normalizedComponent;
		const match2 = k === `${normalizedComponent}/index`;
		const match3 = k.endsWith(`/${normalizedComponent}`);
		const match4 = k.endsWith(`/${normalizedComponent}/index`);
		
		return match1 || match2 || match3 || match4;
	});
	
	if (matchKeys?.length >= 1) {
		const matchKey = matchKeys[0];
		// 只为APP相关组件输出日志
		if (normalizedComponent.includes('app-management')) {
			console.log(`✅ [APP组件] 匹配成功: ${normalizedComponent} -> ${matchKey}`);
		}
		return dynamicViewsModules[matchKey];
	}
	
	// 如果没有找到，尝试更宽松的匹配
	const fuzzyMatchKeys = keys.filter((key) => {
		const k = key.replace(/^\.\.\/views\//, '').replace(/\.vue$/, '');
		return k.includes(normalizedComponent) || normalizedComponent.includes(k);
	});
	
	if (fuzzyMatchKeys.length > 0) {
		if (normalizedComponent.includes('app-management')) {
			console.log(`🔍 [APP组件] 模糊匹配成功: ${normalizedComponent} -> ${fuzzyMatchKeys[0]}`);
		}
		return dynamicViewsModules[fuzzyMatchKeys[0]];
	}
	
	// 最后尝试：直接匹配文件名
	const fileNameMatchKeys = keys.filter((key) => {
		const fileName = key.split('/').pop()?.replace(/\.vue$/, '');
		const componentFileName = normalizedComponent.split('/').pop();
		return fileName === componentFileName || (fileName === 'index' && componentFileName === 'index');
	});
	
	if (fileNameMatchKeys.length > 0) {
		if (normalizedComponent.includes('app-management')) {
			console.log(`📄 [APP组件] 文件名匹配成功: ${normalizedComponent} -> ${fileNameMatchKeys[0]}`);
		}
		return dynamicViewsModules[fileNameMatchKeys[0]];
	}
	
	// 只为关键组件输出错误日志
	if (normalizedComponent.includes('app-management') || normalizedComponent.includes('testing')) {
		console.error(`❌ [组件匹配] 无法找到组件: ${component}`);
	}
	
	// 返回一个空组件而不是undefined，避免路由注册失败
	return () => import('../views/error/404.vue').catch(() => {
		// 如果连404页面都没有，返回一个简单的组件
		return {
			template: `<div style="padding: 20px; text-align: center;">
				<h3>组件加载失败</h3>
				<p>无法找到组件: ${component}</p>
				<p>请检查组件路径是否正确</p>
			</div>`
		};
	});
}
