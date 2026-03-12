import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// 自定义 Vite 插件：接收前端的保存请求，写回原始文件
function saveSourcePlugin() {
  return {
    name: 'save-source',
    configureServer(server) {
      server.middlewares.use('/api/save', (req, res) => {
        if (req.method !== 'POST') return;
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
          try {
            const { oldText, newText } = JSON.parse(body);
            if (oldText && newText && oldText !== newText) {
              const filePath = path.resolve(__dirname, 'architect.tsx');
              let content = fs.readFileSync(filePath, 'utf-8');

              // 用简单字符串查找替换，避免 regex 特殊字符问题
              // 修复：如果 newText 包含真实换行，为了不破坏 JSX 的 title="xxx" 语法，
              // 我们把它转成 JSX 支持的模板字符串形式，或者直接保留换行（JSX 其实支持属性内换行，只要没被切断）
              // 但最安全的是：如果属性原本是用双引号包的，直接替换就行，因为 JSX 允许双引号内有真实换行。
              const idx = content.indexOf(oldText);
              if (idx !== -1) {
                // 如果是单行变多行，确保写入的是真实的换行符，JSX 是支持双引号内包含真实换行的
                content = content.slice(0, idx) + newText + content.slice(idx + oldText.length);
                fs.writeFileSync(filePath, content, 'utf-8');
                console.log(`[Save] OK: "${oldText}" → "${newText}"`);
              } else {
                console.warn(`[Save] Not found in source: "${oldText}"`);
              }
            }
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ success: true }));
          } catch (err: any) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: err.message }));
          }
        });
      });
    }
  }
}

export default defineConfig({
  plugins: [react(), saveSourcePlugin()],
  root: '.',
  publicDir: 'public',
  server: { open: true },
})
