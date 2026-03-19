import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "osint_username_lookup.py")) ? relativeRoot : FALLBACK_ROOT
}

function resolvePython(root: string) {
  const localPython = path.join(root, ".venv", "bin", "python")
  return fs.existsSync(localPython) ? localPython : "python3"
}

async function run(argv: string[]) {
  const proc = Bun.spawn(argv, {
    stdout: "pipe",
    stderr: "pipe",
    cwd: resolveRoot(),
  })
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])

  if (exitCode !== 0) {
    throw new Error((stderr || stdout || `Command failed with exit code ${exitCode}`).trim())
  }

  return stdout.trim()
}

export default tool({
  description: "Run free local-first username lookup with Maigret or Sherlock.",
  args: {
    username: tool.schema.string().describe("Username or handle to investigate"),
    tool_name: tool.schema.enum(["auto", "maigret", "sherlock"]).default("auto").describe("Preferred free lookup tool"),
    tags: tool.schema.string().default("").describe("Optional Maigret tags such as photo,us,coding"),
    timeout: tool.schema.number().default(20).describe("Per-request timeout in seconds"),
    all_sites: tool.schema.boolean().default(false).describe("Use all Maigret sites instead of the default ranked subset"),
    top_sites: tool.schema.number().default(500).describe("Maigret top sites count when not using all sites"),
    search_variants: tool.schema.boolean().default(false).describe("Search generated username variants as well as the exact username"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "osint_username_lookup.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--username", args.username, "--tool", args.tool_name, "--timeout", String(args.timeout), "--top-sites", String(args.top_sites)]
    if (args.tags) command.push("--tags", args.tags)
    if (args.all_sites) command.push("--all-sites")
    if (args.search_variants) command.push("--search-variants")
    return run(command)
  },
})
