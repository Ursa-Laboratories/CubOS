// @vitest-environment node
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { createServer, normalizePath } from 'vite'
import { expect, it } from 'vitest'

it.skipIf(process.platform === 'win32')(
  'keeps an imported project path from authorizing the matching absolute host path',
  async () => {
    const directory = await mkdtemp(join(tmpdir(), 'cubos-vite-fs-'))
    const root = join(directory, 'project')
    const hostFile = normalizePath(join(directory, 'private.js'))
    const projectFile = join(root, hostFile)
    const secret = 'HOST_FILE_MUST_NOT_BE_SERVED'
    let server: Awaited<ReturnType<typeof createServer>> | undefined

    try {
      await mkdir(dirname(projectFile), { recursive: true })
      await writeFile(hostFile, secret)
      await writeFile(projectFile, 'export default "project file"')
      await writeFile(join(root, 'main.js'), `import ".${hostFile}"`)
      server = await createServer({
        configFile: false,
        root,
        logLevel: 'silent',
        server: { host: '127.0.0.1', port: 0, fs: { allow: [root] } },
        optimizeDeps: { noDiscovery: true, include: [] },
      })
      await server.listen()
      const address = server.httpServer!.address()
      if (!address || typeof address === 'string') throw new Error('Missing Vite port')
      const baseUrl = `http://127.0.0.1:${address.port}`

      const main = await fetch(`${baseUrl}/main.js`)
      expect(main.status).toBe(200)
      expect(await main.text()).toContain(hostFile)

      const allowed = await fetch(`${baseUrl}${hostFile}`)
      expect(allowed.status).toBe(200)
      expect(await allowed.text()).toContain('project file')

      const denied = await fetch(`${baseUrl}/@fs${hostFile}`)
      expect(denied.status).toBe(403)
      expect(await denied.text()).not.toContain(secret)
    } finally {
      await server?.close()
      await rm(directory, { recursive: true, force: true })
    }
  },
)
