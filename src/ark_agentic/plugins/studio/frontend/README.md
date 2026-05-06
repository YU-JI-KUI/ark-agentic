# Ark-Agentic Studio Frontend

Studio UI 基于 React + TypeScript + Vite。

## 本地开发

在当前目录执行：

```bash
npm install
npm run dev
```

默认会启动 Vite 开发服务。

## 如何构建 UI

后端会从 `src/ark_agentic/studio/frontend/dist` 挂载静态资源，因此发布或集成 Studio 前，需要先构建前端产物。

在当前目录执行：

```bash
npm install
npm run build
```

构建成功后会生成：

```text
src/ark_agentic/studio/frontend/dist/
```

其中 `npm run build` 实际执行的是：

```bash
tsc -b && vite build
```

## 与后端集成

当环境变量 `ENABLE_STUDIO=true` 时，后端会尝试挂载 Studio：

- API 前缀：`/api/studio`
- UI 入口：`/studio`
- 静态资源目录：`/studio/assets`

如果 `dist` 不存在，后端不会提供 UI，并会提示先在 `studio/frontend/` 下运行 `npm run build`。

## 可选检查

构建完成后可执行：

```bash
npm run preview
```

用于本地预览构建后的 UI。
