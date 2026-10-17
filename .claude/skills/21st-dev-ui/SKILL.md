---
name: 21st-dev-ui
description: Look up ready-made React/Tailwind UI components on 21st.dev (heroes, pricing tables, forms, dashboards, navbars, buttons, logos) and install or adapt them. Use only when the user asks for a UI component, UI inspiration, or mentions 21st.dev. Optional helper, never required.
---

# 21st.dev UI lookup (optional)

21st.dev is a community registry of React components built on Tailwind and shadcn/ui.
This skill is a side tool. Do not add 21st.dev components unless the user asks for a
UI piece, asks for inspiration, or names 21st.dev. Never install anything just
because this file exists.

When the user says something like "get a pricing section from 21st.dev" or "use 21st
for the navbar", that is the go-ahead: go to the site yourself, find matching
components, and bring them back. Don't ask the user to browse the site for you.

## 1. Check the project fits

21st.dev components are React + Tailwind (+ usually shadcn/ui). Before suggesting one:

- Look for `package.json` with `react`, a Tailwind config or `@tailwindcss/*`, and a
  shadcn `components.json`.
- If the project has React + Tailwind but no `components.json`, offer to run
  `npx shadcn@latest init` first and ask before doing it.
- If the project is not React (Python, Unity, plain HTML, Angular, a static Pages
  site): say so in one line. Offer to use the component only as a visual reference
  and rebuild it by hand in the project's own stack, or skip it.

## 2. Find components

Prefer the first option that is available:

1. **21st MCP tools** (if connected in this session): `get_inspiration` to browse,
   `generate` to build a component from a description, `search_logo` for brand logos.
2. **Markdown pages via WebFetch** (no key needed to read):
   - Category listing: `https://21st.dev/community/components/s/<tag>.md`
     (tags like `hero`, `pricing`, `forms`, `dashboard`, `navbar`, `footer`, `card`,
     `table`, `modal`, `sidebar`, `testimonials`, `cta`)
   - Single component: `https://21st.dev/@<author>/components/<slug>.md`
     (shows description, license, npm dependencies, preview link, install command)
   - Site overview for agents: `https://21st.dev/llms.txt`
3. **WebSearch** with `site:21st.dev <what you need>` if the category pages miss.
4. **A real browser** when you need to see the live preview, compare how components
   look, or copy code from a page that needs the user's 21st.dev login. Use whichever
   agent browser is available, in this order:
   - **ego lite** (`/ego-browser` skill, installed with `npx skills add citrolabs/ego-lite`):
     runs in the user's own logged-in browser in a separate Space, so 21st.dev
     sign-in already works. macOS only for now.
   - **Claude in Chrome** or the desktop app's built-in browser, if those tools are
     in the session.
   Open `https://21st.dev/community/components/s/<tag>`, open the candidates, take a
   screenshot of each preview to show the user, and read the code tab. Stay on
   21st.dev; don't sign in, buy anything, or change account settings.

Show the user 2 to 4 candidates with: name, author, what it looks like, npm
dependencies, license, and the preview link. Let them pick before installing.

## 3. Install the chosen component

Installs need a free 21st.dev API key (generate one at https://21st.dev/mcp; free
accounts have a daily install limit). The key lives in the environment variable
`API_KEY_21ST`. Never write the key into a file in the repo or into a commit.

```bash
npx shadcn@latest add "https://21st.dev/r/<author>/<slug>?api_key=$API_KEY_21ST"
```

If `API_KEY_21ST` is not set, tell the user how to get one and stop. Do not ask
them to paste the key into chat.

After installing:

- Read the new files (usually under `components/ui/`) before using them.
- Adapt colors, fonts, copy and spacing to the project's existing design tokens
  instead of leaving the demo styling.
- Remove demo placeholder text and images.
- Run the project's build or type check.

## 4. Optional: connect the 21st MCP

Only if the user wants the MCP tools available permanently:

```bash
npx @21st-dev/cli@latest init --client claude
```

This is a per-machine setup, not something to commit to the repo.

## Rules

- Ask before installing; list the npm packages it will add.
- Check the license on the component page (most are MIT).
- One component at a time; don't bulk-install a library.
- No em dashes or double hyphens in any copy you write into the UI.
