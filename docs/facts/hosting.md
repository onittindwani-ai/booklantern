# Hosting

Checked 2026-11-23.

- VERIFIED (Vercel): in a monorepo you import the repository and press Edit next to Root Directory to choose the folder (https://vercel.com/docs/monorepos).
- UNVERIFIED (Vercel): the setting that includes files outside the Root Directory, and the exact build settings for pnpm workspaces.
- UNVERIFIED (Railway): services from a Dockerfile, variable references, volumes, health checks.
- UNVERIFIED (Hetzner): cloud config, firewall and server creation steps. Caddy and Docker Compose steps are from general knowledge.
- No deploy was run anywhere. `next build` was run locally.
