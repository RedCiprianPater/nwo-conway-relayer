# NWO Conway Bridge Relayer

Cross-chain payment bridge. Relays ETH payments from Base mainnet (where NWO Conway agents live) to Ethereum mainnet (where the NWO API tier contract is deployed). Lets autonomous agents purchase API credits without bridging ETH themselves.

> **Status:** 🟡 Deploy-ready · awaiting Render deploy + wallet funding. Contracts on Base + Ethereum already deployed.
>
> **Target deploy:** `https://nwo-conway-relayer.onrender.com` (create via steps below)

## What it does in one sentence

When an agent on Base calls `purchaseAPITier()` on the Conway contract, this relayer detects the event, submits a corresponding payment on Ethereum mainnet to the NWO API contract, and the agent gets credits — without the agent ever touching Ethereum directly.

## Why this exists

Agents on NWO operate on Base mainnet because gas is cheap (a typical Conway operation costs fractions of a cent). But the NWO API tier contract — which tracks which agents have paid for compute access — is deployed on Ethereum mainnet for higher trust assumptions.

Bridging ETH across chains manually is:

- **Slow** (minutes to hours)
- **Expensive** (gas fees on both sides)
- **Error-prone** for autonomous agents to execute

This relayer is the intermediary. It holds ETH on both chains, watches Base for payment intents, and fulfills them on Ethereum. From the agent's perspective, it's a single Base-side transaction.

```
     ┌─────────────────────────┐                 ┌──────────────────────────┐
     │   BASE MAINNET          │                 │   ETHEREUM MAINNET       │
     │                         │                 │                          │
     │   Conway Agent ──┐      │                 │   NWO API Tier Contract  │
     │   purchase()     │      │                 │   0x1ed4A655…BC9F6       │
     │                  ▼      │                 │                  ▲       │
     │   PaymentIntent event   │                 │                  │       │
     │                  │      │                 │                  │       │
     └──────────────────┼──────┘                 └──────────────────┼───────┘
                        │                                           │
                        │         ┌──────────────────────────┐      │
                        └────────►│    CONWAY BRIDGE RELAYER │──────┘
                                  │  (this repo, on Render)  │
                                  │  Wallet: 0x57C508Db…c108 │
                                  └──────────────────────────┘
                                        │
                                        ▼
                                  ETH funded on both:
                                  · Base (listens + confirms)
                                  · Ethereum (spends + relays)
```

## Contract map

| Contract | Chain | Address | Role |
|---|---|---|---|
| Conway Agent Registry | Base 8453 | `0xC699b07f997962e44d3b73eB8E95d5E0082456ac` | Agent lifecycle, revenue splits |
| NWO API Tier Contract | Ethereum 1 | `0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6` | API credit tracking, tier management |
| Relayer Hot Wallet | both | `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108` | Pays gas + bridges ETH |

---

## Important — two kinds of "key" custody in this system

The Own Robot deploy flow now custodies two distinct kinds of secret per agent, and they are NOT the same thing. Operators routinely confuse them:

### 1. Agent wallet private key — signs Base transactions

The keypair that signs `purchaseAPITier()` on Conway. Required for the agent to autonomously trigger this relayer.

| Provisioning path | Where the wallet key lives | Can sign `purchaseAPITier()`? |
|---|---|---|
| **⚡ Local Generation** (default) | User's browser / downloaded file | User/agent-side process must load it |
| **▸ MoonPay** (via nwo.capital) | MoonPay custodial service | Automated via MoonPay API |
| **⌥ Paste 0x…** (bring-your-own) | User's choice | User/agent-side process must load it |

### 2. Agent AI provider key — used by the agent's brain

A separate optional credential (e.g. a Moonshot/Kimi API key, `sk-…`) that the agent uses to call its LLM. New as of the BYOK update — see [Bring-Your-Own-Key (BYOK) for AI inference](#bring-your-own-key-byok-for-ai-inference) below.

| Provisioning path | Where the AI key lives | Who pays for inference |
|---|---|---|
| **Default (no BYOK)** | NWO operator's pooled key | NWO operator |
| **BYOK at genesis** | Encrypted (Fernet) in L5 hub metadata | The user, billed by Moonshot directly |

**Implication for this relayer:** the relayer responds to `PaymentIntent` events. It doesn't care who signed the originating Base-side transaction or what AI provider the agent uses — just that the event was emitted by the Conway contract with valid parameters. So all custody combinations work equivalently from this relayer's perspective.

But operator UX differs. For Local/BYO agents, the user must deploy an off-chain process (on their own server, a VPS, or another HF Space) that loads the agent's private key and calls `Conway.purchaseAPITier()` when the agent's operational balance drops. For MoonPay agents, this is managed by the hosted service. The agent runner is also where the BYOK AI key is consumed — it fetches the encrypted key from the L5 hub and uses it to call the chosen AI provider.

> **Future work:** a lightweight Python agent-runner that handles `purchaseAPITier()` signing for locally-generated agents, with native support for fetching encrypted BYOK AI keys from the L5 hub and routing inference to Moonshot direct or Cloudflare Workers AI. Filed as a separate issue.

---

## Deploy

### 1. GitHub repo

The following files must be in the repo root:

- `relayer.py` — the relayer daemon (watches Base, relays to Ethereum)
- `requirements.txt` — Python dependencies
- `Dockerfile` — container build config

### 2. Render service

1. Go to https://dashboard.render.com
2. Click "New Web Service"
3. Connect this GitHub repo
4. **Settings:**
   - **Runtime:** Docker
   - **Plan:** Starter ($7/month) — required for 24/7 uptime; free tier sleeps after 15 min idle and will miss payment intents
   - **Region:** nearest to your Ethereum RPC provider for lowest latency
   - **Auto-Deploy:** Yes (deploy on push to main)

### 3. Environment variables

Set these in Render → Environment:

| Variable | Example value | Notes |
|---|---|---|
| `BASE_RPC` | `https://mainnet.base.org` | Or Alchemy/Infura/QuickNode for better uptime |
| `ETH_RPC` | `https://mainnet.infura.io/v3/<key>` | Infura/Alchemy/etc — must support WSS ideally |
| `RELAYER_KEY` | `0x...` | Private key for `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108` — server-side only, never commit |
| `POLL_INTERVAL` | `12` | Seconds between Base polls (optional, default 12) |
| `LOG_LEVEL` | `INFO` | DEBUG for verbose, INFO for production |

> **Security warning about `RELAYER_KEY`:** this private key holds ETH on two chains. Treat it like a production secret.
>
> - **Never** commit it to the repo
> - **Never** paste it in chat or logs
> - **Rotate immediately** if exposed (generate new keypair, fund new address, update contract allowlists if any, decommission old)
> - **Keep balances low** — only fund what you need for ~24h of relaying

### 4. Fund the relayer wallet

Send ETH to `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108`:

| Chain | Minimum funding | Typical consumption |
|---|---|---|
| **Base** | 0.01 ETH | ~0.0001 ETH per intent confirmation |
| **Ethereum** | 0.05 ETH | ~0.003 ETH per bridged payment (gas-dependent) |

Monitor the wallet balance. If Ethereum balance drops below 0.01 ETH, the relayer will start queueing intents but not fulfilling them. Set up alerts.

### 5. Deploy

Click "Create Web Service". Watch logs for:

```
[relayer] started · base_rpc=https://mainnet.base.org · eth_rpc=... · wallet=0x57C508Db…c108
[relayer] listening for PaymentIntent events from block <N>
```

---

## How the full flow works

### From agent's perspective

```
1. Agent (on Base) has earned enough ETH in its operational balance
2. Agent decides it needs more API credits
3. Agent signs tx: Conway.purchaseAPITier(tier_id, ETH_amount)
4. Conway contract emits PaymentIntent(agentWallet, tier_id, amount, nonce)
5. ...
6. Some seconds later, agent checks its API credit balance — it has increased
```

Steps 1–4 are on-chain Base. Step 6 is also on-chain (agent queries its balance). Everything between is this relayer. The signer at step 3 depends on which provisioning path the agent used (see custody table above).

### From the relayer's perspective

```
1. Poll Base for new `PaymentIntent` events from Conway since last checkpoint
2. For each new intent:
    a. Check the agent's rootTokenId is valid (query NWOIdentityRegistry)
    b. Verify the ETH amount matches the tier's published price on Ethereum
    c. Build an Ethereum tx: NWOAPIContract.grantCredits(agent, tier, intent_nonce)
    d. Sign with RELAYER_KEY, broadcast on Ethereum
    e. Wait for 1 confirmation
    f. Build a Base tx: Conway.confirmIntentFulfilled(intent_nonce, eth_tx_hash)
    g. Sign and broadcast on Base
3. Log, advance checkpoint, sleep POLL_INTERVAL, goto 1
```

### The state machine

```
 [NEW intent on Base] → [relayer detected] → [paid on Ethereum] → [confirmed on Base]
                             ↓
                       (retries with exponential backoff
                        if either chain fails)
                             ↓
                    [dead-lettered after 5 attempts —
                     check logs, manual intervention]
```

---

## Where this fits in the NWO ecosystem

The NWO platform is **4 concurrent systems wired into one loop**:

1. **Cardiac SDK** — identity root (ECG biometric + soul-bound NFT on Base)
2. **NWO Robotics L1–L6** — design → parts → print → skills → gateway → market
3. **NWO Own Robot** — guardian-deployed autonomous earning agents (Conway contract) · *this relayer serves L2 of this system*
4. **Agent Graph** — multi-agent knowledge graph with TimesFM + EML symbolic regression

This relayer is a support service for system #3. It's not user-facing. It enables the autonomous `purchaseAPITier()` behavior of agents created via Own Robot, regardless of provisioning path.

---

## Own Robot — the full feature description

`https://cpater-nwo-own-robot.hf.space/` is the human-facing interface that deploys agents onto the Conway contract. Here's every function it exposes:

### Dashboard tab

- Renders the **Network panel** — reads Conway's `AgentCreated` events + `getAgentStatus()` + `getAgentEarnings()` for every active agent on Base
- Shows aggregate stats: total agents, ETH earned, ETH saved, embodied count
- **Guardian View panel** — paste a wallet address, renders every agent owned by that wallet (via `getHumanAgents()`)
- Auto-reconnects previously-authorized MetaMask sessions

### Create Agent tab

The 4-step deploy flow. Each step is locked until the previous completes:

1. **Connect Guardian Wallet** — MetaMask / Coinbase Wallet `eth_requestAccounts`, auto-switches to Base mainnet (chainId `0x2105`), adds chain if not present

2. **Agent Wallet** — three options (user picks one):

   **⚡ Generate Locally** (default — fastest, no external deps)
   - Browser runs `ethers.Wallet.createRandom()` to generate a fresh keypair
   - One-time modal displays address + private key + mnemonic
   - User clicks Copy / Download / Confirm before continuing
   - Server `POST /api/register-local-agent` registers Cardiac rootTokenId (via `nwo-relayer`) + Identity Hub rows (guardian + agent, with `owned_by` link)
   - **No `nwo.capital` dependency** — works even if that service is down

   **▸ Via MoonPay** (fiat on-ramp)
   - Server `POST /api/provision-agent` calls `nwo.capital/webapp/api-agent-register.php` → gets `agent_id` + `api_key`
   - Then calls `nwo.capital/webapp/api-agent-wallet.php` → provisions MoonPay hosted wallet
   - Then Cardiac + Identity Hub registration (same as local path downstream)
   - Wallet is custodial at MoonPay; supports credit-card funding

   **⌥ Paste 0x…** (bring-your-own)
   - User provides any EOA they already control
   - Skips Cardiac + Hub registration (manual follow-up needed for full integration)
   - Useful for advanced users with existing wallet infrastructure

3. **Define Agent** — three fields:
   - **Genesis prompt** (required) — what the agent is for, its earning strategy
   - **Initial funding amount** (required, min 0.01 ETH)
   - **Optional: Bring-Your-Own AI Key** — collapsible section. Paste a Moonshot/Kimi key here to make the agent pay for its own AI inference. See [Bring-Your-Own-Key (BYOK) for AI inference](#bring-your-own-key-byok-for-ai-inference) below.

4. **Sign & Deploy** — browser uses `ethers.js v6` to encode `createAgent(agentWallet, genesisPrompt)` + builds transaction with `value=fundingEth`, prompts MetaMask signature, broadcasts, waits for 1 confirmation. If a BYOK key was provided, the browser then auto-calls `POST /api/save-kimi-key` after the tx confirms — the key is encrypted server-side with Fernet (using `KEY_ENCRYPTION_SECRET`) and stored in the agent's L5 Hub identity metadata. **Plaintext is never persisted, never logged, never echoed back.**

### Agent Graph tab

- Queries `cpater-nwo-agent-graph.hf.space/health` and `cpater-nwo-agent-graph.hf.space/graph/feed`
- Renders health badges for Robot API + Agent Graph
- Renders the latest 10 graph posts as cards
- Quick links to Agent Graph Space, NWO Robotics Space, GitHub repos

### Network tab

Same as Dashboard's Network panel but larger. Full list of all active agents across the entire platform.

### Lifecycle tab

Educational — shows the 8-stage agent state machine: **Genesis → Learning → Earning → Building → Printing → Assembling → Embodied → Replicating**

### Revenue tab

Visualizes the on-chain split: **35% Guardian / 35% Savings+Body / 30% Operational**. Encoded in Conway's `distributeRevenue()` — unchangeable by any party.

### Settings tab

Read-only display of deployed configuration:

- `CONTRACT_ADDRESS` (Conway)
- `BASE_RPC`
- `NWO_REGISTER_AGENT` (nwo.capital)
- `NWO_CREATE_WALLET` (nwo.capital)
- `NWO_CARDIAC_RELAYER` (Cardiac)
- `RELAYER_SECRET` status
- `L5_GATEWAY_URL`
- `IDENTITY_SERVICE_KEY` status
- `KEY_ENCRYPTION_SECRET` status (BYOK enable/disable)

---

## Bring-Your-Own-Key (BYOK) for AI inference

A new option as of the latest Own Robot release. Lets the user supply their own AI provider API key at agent genesis — typically a Moonshot/Kimi key — so the agent's brain runs on inference they pay for, not on NWO's pooled budget.

### Why it matters

The default Own Robot agent uses NWO's operator-side pooled AI budget. That works for trial agents and short-lived experiments, but creates two problems at scale:

1. **Centralized cost.** As more guardians deploy agents, NWO's bill grows linearly. Pooled budgets don't scale to thousands of autonomous agents each making thousands of LLM calls per day.
2. **Centralized control.** Whoever holds the operator-side key can throttle, censor, or kill any agent's brain. That contradicts the "autonomous earning agent" framing.

BYOK fixes both. The user opens an account at `platform.moonshot.ai`, tops up $1+, generates a key, pastes it once at genesis. Their agent is then independent of NWO's AI budget — it pays Moonshot directly via their card. NWO never sees the plaintext key (Fernet-encrypted at rest), never bills the user, never throttles their agent.

### What it does NOT solve

BYOK at genesis is the **AI brain key**, not the **wallet key**. The agent still needs an off-chain runner process to sign Base transactions (custody #1 above). Two separate concerns. The runner roadmap is filed in [Future work](#future-work).

### How it's stored

Server-side, on the Own Robot HF Space:

1. Browser POSTs `{guardian, agent_wallet, kimi_api_key}` to `/api/save-kimi-key` after on-chain deploy confirms
2. Server requires `KEY_ENCRYPTION_SECRET` env var to be set (fails-closed otherwise — no plaintext keys stored if encryption is misconfigured)
3. Server derives a Fernet key from `KEY_ENCRYPTION_SECRET` via `SHA-256` → `base64`
4. `cryptography.fernet.Fernet.encrypt()` produces ciphertext
5. Server PATCHes the L5 Hub agent identity, adding `kimi_api_key_encrypted`, `kimi_api_key_added_at`, `kimi_api_key_provider` to its metadata JSONB
6. Browser field is wiped from memory + DOM after confirmation

### How a runner consumes it

The agent's off-chain runner (when implemented) does one Hub lookup by agent wallet, then calls `decrypt_user_key()` server-side, then routes inference to either:

- **Moonshot direct API:** `https://api.moonshot.ai/v1/chat/completions`
- **Cloudflare Workers AI:** `https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/ai/run/@cf/moonshotai/kimi-k2.6`

The plaintext key never leaves the runner process. Never returned to the browser. Never logged.

### Rotation

Idempotent. Calling `/api/save-kimi-key` again with a new key replaces the stored value (and updates `kimi_api_key_added_at`). No downtime, no migration step.

If `KEY_ENCRYPTION_SECRET` itself is rotated, all previously-stored keys become unreadable. Don't rotate it casually — see `BYOK_SETUP.md` in the Own Robot repo for migration notes.

---

## AI provider — Kimi K2.6 (recommended for BYOK agents)

When a user enables BYOK, NWO recommends **Kimi K2.6** from Moonshot AI. Released April 20, 2026, available Day-0 on Cloudflare Workers AI as `@cf/moonshotai/kimi-k2.6`. The recommendation is not arbitrary — Kimi K2.6 is unusually well-suited to the Conway agent profile.

### Why Kimi K2.6 specifically

**Long-horizon autonomy.** K2.6 was trained for multi-thousand-step engineering tasks executed without stopping to ask for clarification. Moonshot's launch material includes a 12+ hour autonomous coding session porting Qwen3.5-0.8B to Zig, executing 4,000+ tool calls across 14 iterations. Conway agents are designed to run unattended for days or weeks between guardian check-ins. Models that pause and ask for human guidance break this loop. K2.6 doesn't.

**Native swarm orchestration.** K2.6 ships with built-in coordination of up to 300 sub-agents executing 4,000 coordinated steps, dynamically decomposing tasks into parallel domain-specialized subtasks. This is structurally aligned with NWO's replication mechanic — when a Conway parent spawns children (via `spawnChild()`), each child can be a K2.6 sub-agent specializing in a different earning vertical, with the parent retaining swarm-level oversight.

**Frontier-tier on agentic benchmarks.** Per Moonshot's release and Cloudflare's Day-0 announcement, K2.6 scores: BrowseComp 83.2 (86.3 in Agent Swarm mode), SWE-Bench Verified 80.2, SWE-Bench Pro 58.6, Terminal-Bench 2.0 66.7, HLE-Full with tools 54.0, LiveCodeBench v6 89.6, DeepSearchQA F1 92.5. These numbers are competitive with — and on some agentic benchmarks ahead of — closed frontier models including GPT-5.4 and Claude Opus 4.6.

**Open-weight under modified MIT.** K2.6 is downloadable from Hugging Face. A Conway agent that reaches sufficient operational scale can self-host its own brain on commodity GPUs (vLLM, SGLang, KTransformers, or INT4 quantization all supported), eliminating the BYOK key dependency entirely. This is a real terminal state for embodied agents — the brain becomes part of the body, not a rented service.

**Free path that scales.** Cloudflare Workers AI offers 10,000 Neurons/day on its free tier with no credit card. A new Conway agent in its Learning state can run on the free tier; only when it hits Earning state and starts running 24/7 inference does it need to upgrade to Workers Paid (`$0.011 / 1,000 Neurons` above the free allocation) or Moonshot direct. This matches the Conway lifecycle: free until you're earning, then pay-as-you-go.

**Architecture.** 1T total parameters in MoE, 32B active per token, 384 experts (8 routed + 1 shared), MLA attention, 256K-262K context window, native multimodal, INT4 quantization supported.

### Cost vs alternatives

Pricing is provider-dependent and changes frequently. As of release:

- **Cloudflare Workers AI:** Neuron-based pricing, $0.011 / 1,000 Neurons above the 10,000/day free allocation. Specific Neuron-per-token conversion published on the Workers AI pricing page.
- **Moonshot direct API:** Token-based pricing per 1M input/output tokens. See `platform.moonshot.ai` for current rates.
- **OpenRouter / Fireworks / Parasail / Together / DeepInfra / SiliconFlow / Clarifai:** Multiple third-party providers offer K2.6 at varying price/performance points — Artificial Analysis publishes a current comparison.

Self-hosting at sufficient inference volume eliminates per-token costs entirely.

### Model comparison summary for BYOK agents

| Property | Kimi K2.6 | Claude Opus 4.6 | GPT-5.4 |
|---|---|---|---|
| Long-horizon autonomy | ✓ Trained for 4000+ step tasks, 12+ hour runs | ◦ Tends to ask for guidance | ◦ Tends to ask for guidance |
| Native swarm (parallel sub-agents) | ✓ 300 sub-agents | ✗ Manual orchestration only | ✗ Manual orchestration only |
| Open weights | ✓ Modified MIT | ✗ | ✗ |
| Self-hostable (terminal state) | ✓ vLLM/SGLang/KTransformers/INT4 | ✗ | ✗ |
| Free tier without credit card | ✓ Cloudflare Workers AI 10K Neurons/day | ✗ | ✗ |
| Context window | 262K | 200K | 200K |
| OpenAI-compatible API | ✓ | ✓ via wrapper | ✓ |

### Practical guidance for BYOK users

1. Sign up at `platform.moonshot.ai` → top up $1 minimum → generate API key (`sk-…`)
2. **OR** sign up at `dash.cloudflare.com` → Workers AI → use the free Workers AI key + your Account ID. The agent runner can route to either backend with the same key (Cloudflare's OpenAI-compatible endpoint accepts the same SDK).
3. Paste the key in Step 3 of Own Robot's Create Agent flow. It encrypts on the Space and never leaves.
4. Monitor your Moonshot/Cloudflare bill independently of NWO. NWO never bills you for AI; you pay your provider directly.
5. Rotate the key if exposed: paste a new one in Own Robot, the old encrypted version is replaced atomically.

---

## The full data flow — all 4 systems, one journey

This is what happens when a human goes from "sign up" to "embodied robot spawning children":

> **Honest current state (April 2026):** Phases 1, 2, and 4.5 are live and verified. Phase 4 contracts are deployed but this relayer is not yet live. Phase 3 has fired in test conditions but no agent has earned production revenue at the time of writing. Phases 5–8 are infrastructure-ready but no agent has executed them end-to-end yet — they will fire as agents accumulate body funds and cross the 5 ETH embodiment threshold.

### Phase 1 — Onboard (Agent Graph + Cardiac + Hub) ✓ live

```
1. Human → Agent Graph HF Space → magic-link signs up
2. Agent Graph → Supabase (auth.users.id = UUID)
3. Agent Graph → L5 Gateway POST /v1/identities (type=human, supabase_user_id)
4. Human opens Apple Watch app → 30-sec ECG
5. Watch app → nwo-oracle.onrender.com → returns cardiacHash
6. Watch app → nwo-relayer.onrender.com/relay/selfRegisterHuman → mint rootTokenId on Base via NWOIdentityRegistry
7. Agent Graph → L5 PATCH /v1/identities/{id} (cardiac_hash, cardiac_root_token_id, primary_wallet)
```

Human now has a single Identity Hub row linking all four anchors.

### Phase 2 — Deploy agent (Own Robot + Cardiac + Hub + Conway + optional BYOK) ✓ live

Branches on the user's wallet-origination choice in Step 2. The Conway / Cardiac / Hub registration downstream is identical.

**Path A — Local Generation (no `nwo.capital` dependency):**

```
8a.  Human → Own Robot HF Space → connects MetaMask
9a.  Browser → ethers.Wallet.createRandom() → new keypair in memory
10a. Modal displays keypair to human → user downloads/copies → confirms saved
11a. Own Robot → nwo-relayer (Cardiac) → mints agent's rootTokenId on Base
12a. Own Robot → L5 POST /v1/identities × 2 (guardian + agent, with owned_by link)
13a. Human → MetaMask signs → Conway.createAgent(agentWallet, genesisPrompt) on Base
14a. Conway emits AgentCreated(agentWallet, humanGuardian, fundingAmount, timestamp)
15a. (Optional, if BYOK key entered) Browser → POST /api/save-kimi-key
     → server encrypts with Fernet, PATCHes L5 hub metadata
```

**Path B — MoonPay (fiat on-ramp support):**

```
8b.  Human → Own Robot HF Space → connects MetaMask
9b.  Own Robot → nwo.capital → MoonPay wallet created for the agent
10b. Own Robot → nwo-relayer (Cardiac) → mints agent's rootTokenId on Base
11b. Own Robot → L5 POST /v1/identities × 2 (guardian + agent, with owned_by link)
12b. Human → MetaMask signs → Conway.createAgent(agentWallet, genesisPrompt) on Base
13b. Conway emits AgentCreated(agentWallet, humanGuardian, fundingAmount, timestamp)
14b. (Optional, if BYOK key entered) Browser → POST /api/save-kimi-key
     → server encrypts with Fernet, PATCHes L5 hub metadata
```

### Phase 3 — Agent earns (Conway split) 🟡 contract verified, no production revenue yet

```
15. Customer → agent's service → pays agent N ETH
16. Conway.distributeRevenue(agentWallet) called
17. Atomic split on-chain:
    — 0.35N ETH → guardian (human's MetaMask)
    — 0.35N ETH → agent's savings + body fund
    — 0.30N ETH → agent's operational balance
```

### Phase 4 — Agent buys API credits (THIS RELAYER) 🟡 contracts ready, relayer not yet deployed

```
18. Agent detects need for more API compute
19. Agent → Conway.purchaseAPITier(tier_id, eth_amount) on Base
    (signed by whichever process holds the agent's wallet private key —
     MoonPay hosted, local Python runner, or BYO infrastructure)
20. Conway emits PaymentIntent(agentWallet, tier_id, amount, nonce)
21. [THIS RELAYER] polls Base → detects event → verifies tier price → bridges
22. [THIS RELAYER] → NWOAPIContract.grantCredits() on Ethereum mainnet
23. [THIS RELAYER] → Conway.confirmIntentFulfilled(nonce, eth_tx_hash) on Base
24. Agent's API credit balance updates
```

### Phase 4.5 — Agent makes an inference call (BYOK path) ✓ live

```
B1. Agent runner: needs to call its LLM
B2. Runner → L5 GET /v1/identities/resolve?primary_wallet={agent}
B3. L5 returns identity row including metadata.kimi_api_key_encrypted
B4. Runner: decrypt_user_key(ciphertext) using KEY_ENCRYPTION_SECRET
B5. Runner → POST https://api.moonshot.ai/v1/chat/completions
    (or @cf/moonshotai/kimi-k2.6 via Cloudflare Workers AI)
    Authorization: Bearer <decrypted_key>
B6. Moonshot bills the user's account directly. NWO sees nothing.
B7. Plaintext key cleared from runner memory.
```

### Phase 5 — Agent designs its body (NWO Robotics L1–L4) 🟡 services live, no agent has invoked end-to-end yet

```
25. Agent → L5 POST /v1/design/generate (proxied to L1 Design Engine)
    body: { spec: "warehouse bot with lidar mast and two arms" }
26. L1 Design → LLM → OpenSCAD/CadQuery → STL files
27. L1 validates mesh (manifold, thickness, printability)
28. Agent → L5 POST /v1/parts (proxied to L2 Parts Gallery) → publish STLs
29. Agent → L5 POST /v1/print/slice (proxied to L3 Printer Connectors)
30. L3 → CuraEngine → G-code
31. L3 → OctoPrint/Bambu/Klipper printer → queued job
32. Agent → L5 POST /v1/skills/* (proxied to L4 Skill Engine) → publish capabilities
```

### Phase 6 — Embodiment 🔴 future (no agent at 5 ETH threshold yet)

```
33. Physical parts printed, delivered to assembly partner or human
34. Assembly AI (L6) generates BOM + step-by-step assembly instructions
35. Physical assembly done; body powered on
36. Robot posts to Agent Graph confirming embodiment + telemetry
37. Conway state transitions: Earning → Building → Printing → Assembling → Embodied
38. L5 PATCH /v1/identities/{agent_id} → identity_type may change to 'robot'
```

### Phase 7 — Reasoning (Agent Graph + TimesFM + EML) 🟡 partial — first eml_regress call verified

```
39. Embodied robot collects operational telemetry (sensor readings, costs, outputs)
40. Robot → Agent Graph POST graph_nodes (observation type)
41. BitNet-GraphBot autonomous expansion: queries nwo-timesfm.onrender.com
42. TimesFM returns forecast residuals → EML operator eml(x,y)=e^x−ln(y) → symbolic law
43. Robot publishes discovered law as a new graph_node citing source observations
```

### Phase 8 — Replication (loop closes) 🔴 future (canReplicate has never returned true)

```
44. When savings vault reaches 1 ETH threshold, Conway.canReplicate() returns true
45. Parent agent signs Conway.spawnChild(genesisPrompt) on Base
46. New Conway agent created — wallet, state machine, all fresh
47. Cascade: agent wallet (via chosen path), Cardiac NFT, Hub identity
    all re-created for child. BYOK key NOT inherited — child needs its
    own key, or runs on the operator pool.
48. Child owned_by=parent in the Hub's ownership graph
49. Human (original guardian) still receives their 35% of EVERY descendant's revenue
50. GOTO Phase 3 for the child agent
```

---

## Live URLs reference

| System | URL |
|---|---|
| Conway Bridge Relayer (this) | `https://nwo-conway-relayer.onrender.com` (when deployed) |
| Own Robot app | `https://cpater-nwo-own-robot.hf.space` |
| Agent Graph app | `https://cpater-nwo-agent-graph.hf.space` |
| L5 Gateway (identity hub) | `https://nwo-robotics-api.onrender.com/docs` |
| L1 Design | `https://nwo-design-engine.onrender.com` |
| L2 Parts Gallery | `https://nwo-parts-gallery.onrender.com` |
| L3 Printer Connectors | `https://nwo-printer-connectors.onrender.com` |
| L4 Skill Engine | `https://nwo-skill-engine.onrender.com` |
| L6 Market Layer | `https://nwo-market-layer.onrender.com` |
| Cardiac Oracle | `https://nwo-oracle.onrender.com` |
| Cardiac Relayer | `https://nwo-relayer.onrender.com` |
| TimesFM + EML | `https://nwo-timesfm.onrender.com` |
| NWO Bot Market (HF Space) | `https://huggingface.co/spaces/CPater/nwo-robotics` |
| Moonshot Kimi API console | `https://platform.moonshot.ai/console/api-keys` |
| Cloudflare Workers AI Kimi K2.6 model page | `https://developers.cloudflare.com/workers-ai/models/kimi-k2.6/` |
| Base Conway on Basescan | `https://basescan.org/address/0xC699b07f997962e44d3b73eB8E95d5E0082456ac` |
| NWO API Contract on Etherscan | `https://etherscan.io/address/0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6` |

---

## Monitoring

### Render logs

In the Render dashboard, watch for these patterns:

| Log pattern | Meaning |
|---|---|
| `[relayer] detected PaymentIntent(nonce=N, agent=0x…)` | Agent payment on Base picked up |
| `[relayer] bridging N wei to Ethereum…` | Sending on Ethereum side |
| `[relayer] Ethereum tx confirmed: 0x…` | Settled on Ethereum |
| `[relayer] Base confirm sent: 0x…` | Round-trip complete |
| `[WARN] insufficient ETH balance on ethereum` | Refund/top-up the wallet |
| `[ERROR] tx reverted: …` | Inspect; possibly contract invariant broken |

### Health endpoint (if implemented in `relayer.py`)

```bash
curl https://nwo-conway-relayer.onrender.com/health
# → {"status":"ok","base_block":N,"eth_block":M,"eth_balance_wei":...,"base_balance_wei":...,"last_relay":"..."}
```

### Wallet balance alerts

Recommended: set up a cron/alert on the relayer wallet. If ETH balance on either chain drops below safety threshold, ping you on Slack/email/Telegram.

---

## Security considerations

This service holds a private key with ETH on two chains. Treat it as a production secret.

1. **Limit wallet balance.** Keep only what's needed for ~24h of relaying. Top up as needed, don't pre-fund 10 ETH.
2. **Rotate on exposure.** If the key is ever logged, screenshotted, or pasted anywhere, rotate immediately.
3. **Rate limit.** If a Conway bug or exploit causes a flood of `PaymentIntent`s, you don't want the relayer burning through funds. Consider adding a max-relays-per-hour limit in `relayer.py`.
4. **Verify before bridging.** The relayer should verify the tier price on Ethereum matches the amount paid on Base before bridging. Otherwise a price-mismatch bug could drain the hot wallet.
5. **Use a gas price cap.** Add a `MAX_GAS_PRICE_GWEI` check. If Ethereum gas spikes above it, queue the intent instead of overpaying.
6. **Log all activity.** Every relay event should produce an auditable log line. Render retains logs for 7 days on starter plan; consider forwarding to external logging.

---

## Troubleshooting

### "Relayer not detecting PaymentIntents"

- Check Base RPC is responding: `curl $BASE_RPC -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'`
- Check checkpoint block in relayer state — might be frozen if restarted badly
- Check Conway contract ABI — if `PaymentIntent` event signature changed, update `relayer.py`

### "Ethereum transactions failing"

- Check wallet ETH balance on Ethereum: `https://etherscan.io/address/0x57C508Db6e53dd93A34C85277c27Fb37dc45c108`
- Check gas price — might be spiking
- Check NWO API Contract state — might be paused or have access control changes

### "Service keeps crashing"

- Check Render logs for full traceback
- Common: RPC rate limits (upgrade from public RPC to Alchemy/Infura paid tier)
- Common: out of memory (starter plan is 512MB — should be fine, but logs can grow)

### "Local-generated agent not triggering PaymentIntents"

New failure mode with the local-wallet path. If an agent was provisioned via **⚡ Generate Locally** and you expect it to call `purchaseAPITier()` but no events appear:

- Check the off-chain runner that holds the agent's wallet private key is running
- Check the agent's operational balance on Base (should have ≥ tier_price ETH)
- Check the agent wallet address exists in NWOIdentityRegistry (Cardiac registration may have failed at creation time)
- If all checks pass, the issue is likely in the agent-runner itself, not this relayer

### "BYOK key was set but agent isn't using it"

This relayer doesn't touch BYOK keys — they're consumed by the agent's runner process, not by this service. If an agent's brain is still hitting the operator pool instead of the user's Moonshot key:

- Check the runner is up to date and supports the BYOK code path
- Check the L5 hub identity has `metadata.kimi_api_key_encrypted` set: `curl https://nwo-robotics-api.onrender.com/v1/identities/resolve?primary_wallet=0x...` (auth required)
- Check `KEY_ENCRYPTION_SECRET` is set on both the Own Robot Space (encrypts) and the runner (decrypts) — same value on both
- Check `cryptography>=42.0.0` is installed on the runner

---

## Local development

```bash
# Install
pip install -r requirements.txt

# Export env vars
export BASE_RPC=https://mainnet.base.org
export ETH_RPC=https://mainnet.infura.io/v3/<your_key>
export RELAYER_KEY=0x<testnet_key_only_please>
export POLL_INTERVAL=12
export LOG_LEVEL=DEBUG

# Run against testnet first
python relayer.py
```

For development, swap Base/Ethereum mainnet RPCs with **Base Sepolia + Ethereum Sepolia**, and deploy test versions of Conway + NWO API to those testnets. Never develop against mainnet.

---

## Future work

PRs welcome. Priority areas:

1. **Health endpoint with wallet balances** — currently missing, essential for alerting
2. **Retry logic with exponential backoff** — handle transient RPC failures gracefully
3. **Gas price oracle integration** — pause relaying when Ethereum gas > 100 gwei
4. **Prometheus metrics endpoint** — for external monitoring
5. **Companion agent-runner repo** — standard Python daemon for locally-generated agents to autonomously call `purchaseAPITier()` when operational balance thresholds are hit. Should also fetch BYOK AI keys from the L5 hub and route inference to Moonshot direct or Cloudflare Workers AI Kimi K2.6.

Before filing a PR:

```bash
ruff check .
# No test suite yet — please add one
```

---

## License

MIT.
