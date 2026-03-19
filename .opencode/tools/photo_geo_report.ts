import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "photo_geo_report.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Generate a structured photo OSINT report from extraction and Maps grounding.",
  args: {
    input: tool.schema.string().describe("Linux path, Windows path, or HTTP/HTTPS URL to an image"),
    query: tool.schema.string().default("Describe nearby places, restaurants, POIs and current conditions within 15-minute walk").describe("Maps grounding prompt"),
    vision: tool.schema.boolean().default(true).describe("Use Gemini vision when GPS is missing"),
    lat: tool.schema.number().optional().describe("Optional user-supplied latitude"),
    lng: tool.schema.number().optional().describe("Optional user-supplied longitude"),
    city: tool.schema.string().default("").describe("Optional user-supplied city fallback"),
    format: tool.schema.enum(["json", "markdown"]).default("json").describe("Output format"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "photo_geo_report.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--input", args.input, "--query", args.query, "--format", args.format]
    if (args.vision) command.push("--vision")
    if (args.lat !== undefined) command.push("--lat", String(args.lat))
    if (args.lng !== undefined) command.push("--lng", String(args.lng))
    if (args.city) command.push("--city", args.city)
    return run(command)
  },
})
