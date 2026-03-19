import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "gemini_maps_enrich.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Run Gemini Google Maps grounding for nearby place intelligence.",
  args: {
    query: tool.schema.string().default("Describe nearby places, restaurants, POIs and current conditions within 15-minute walk").describe("Maps grounding prompt"),
    lat: tool.schema.number().optional().describe("Latitude"),
    lng: tool.schema.number().optional().describe("Longitude"),
    city: tool.schema.string().default("").describe("City or area fallback when coordinates are unavailable"),
    enable_widget: tool.schema.boolean().default(false).describe("Request a Google Maps widget context token"),
  },
  async execute(args) {
    if ((args.lat === undefined || args.lng === undefined) && !args.city) {
      throw new Error("Provide lat/lng or a city fallback.")
    }

    const root = resolveRoot()
    const script = path.join(root, "gemini_maps_enrich.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--query", args.query]
    if (args.lat !== undefined) command.push("--lat", String(args.lat))
    if (args.lng !== undefined) command.push("--lng", String(args.lng))
    if (args.city) command.push("--city", args.city)
    if (args.enable_widget) command.push("--enable-widget")
    return run(command)
  },
})
