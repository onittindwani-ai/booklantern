# Hetzner

cloud-init, Caddyfile and a backup script for one small server running docker compose. Steps: `docs/08-DEPLOY-HETZNER.md`. UNVERIFIED: no server was created. The YAML parses, and `backup.sh` is tested with a stand in `docker` command (it works from any folder, keeps no empty dump, writes files only the owner can read).
