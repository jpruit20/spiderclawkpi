import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const distDir = path.resolve(__dirname, '..', 'dist')
const indexPath = path.join(distDir, 'index.html')

const routes = [
  'departments',
  'division/customer-experience',
  'revenue',
  'friction',
  'issues',
  'root-cause',
  'system-health',
  // legacy aliases kept live during the transition
  'commercial',
  'support',
  'ux',
  'diagnostics',
  'source-health',
]

if (!fs.existsSync(indexPath)) {
  throw new Error(`Missing built index.html at ${indexPath}`)
}

const indexHtml = fs.readFileSync(indexPath, 'utf8')

for (const route of routes) {
  const routeDir = path.join(distDir, route)
  fs.mkdirSync(routeDir, { recursive: true })
  fs.writeFileSync(path.join(routeDir, 'index.html'), indexHtml)
}

console.log(`Generated static SPA fallbacks for ${routes.length} routes in ${distDir}`)
