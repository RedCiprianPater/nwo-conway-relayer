# NWO Conway Bridge Relayer

**Cross-chain payment bridge.** Relays ETH payments from Base mainnet (where NWO Conway agents live) to Ethereum mainnet (where the NWO API tier contract is deployed). Lets autonomous agents purchase API credits without bridging ETH themselves.

> **Status:** 🟡 Deploy-ready · awaiting Render deploy + wallet funding. Contracts on Base + Ethereum already deployed.
>
> **Target deploy:** `https://nwo-conway-relayer.onrender.com` (create via steps below)

---

## What it does in one sentence

When an agent on Base calls `purchaseAPITier()` on the Conway contract, this relayer detects the event, submits a corresponding payment on Ethereum mainnet to the NWO API contract, and the agent gets credits — without the agent ever touching Ethereum directly.

---

## Why this exists

Agents on NWO operate on **Base mainnet** because gas is cheap (a typical Conway operation costs fractions of a cent). But the **NWO API tier contract** — which tracks which agents have paid for compute access — is deployed on **Ethereum mainnet** for higher trust assumptions.

Bridging ETH across chains manually is:
- Slow (minutes to hours)
- Expensive (gas fees on both sides)
- Error-prone for autonomous agents to execute

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

---

## Contract map

| Contract                    | Chain      | Address                                      | Role                                     |
|-----------------------------|------------|----------------------------------------------|------------------------------------------|
| Conway Agent Registry       | Base 8453  | `0xC699b07f997962e44d3b73eB8E95d5E0082456ac` | Agent lifecycle, revenue splits          |
| NWO API Tier Contract       | Ethereum 1 | `0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6` | API credit tracking, tier management     |
| Relayer Hot Wallet          | both       | `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108` | Pays gas + bridges ETH                   |

---

## Deploy

### 1. GitHub repo

The following files must be in the repo root:

- `relayer.py` — the relayer daemon (watches Base, relays to Ethereum)
- `requirements.txt` — Python dependencies
- `Dockerfile` — container build config

### 2. Render service

1. Go to https://dashboard.render.com
2. Click **"New Web Service"**
3. Connect this GitHub repo
4. Settings:
   - **Runtime:** Docker
   - **Plan:** Starter ($7/month) — required for 24/7 uptime; free tier sleeps after 15 min idle and will miss payment intents
   - **Region:** nearest to your Ethereum RPC provider for lowest latency
   - **Auto-Deploy:** Yes (deploy on push to main)

### 3. Environment variables

Set these in Render → Environment:

| Variable       | Example value                                        | Notes                                           |
|----------------|------------------------------------------------------|-------------------------------------------------|
| `BASE_RPC`     | `https://mainnet.base.org`                           | Or Alchemy/Infura/QuickNode for better uptime   |
| `ETH_RPC`      | `https://mainnet.infura.io/v3/<key>`                 | Infura/Alchemy/etc — **must support WSS** ideally |
| `RELAYER_KEY`  | `0x...`                                              | Private key for `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108` — **server-side only, never commit** |
| `POLL_INTERVAL`| `12`                                                 | Seconds between Base polls (optional, default 12) |
| `LOG_LEVEL`    | `INFO`                                               | `DEBUG` for verbose, `INFO` for production      |

**Security warning about `RELAYER_KEY`:** this private key holds ETH on two chains. Treat it like a production secret.
- Never commit it to the repo
- Never paste it in chat or logs
- Rotate immediately if exposed (generate new keypair, fund new address, update contract allowlists if any, decommission old)
- Keep balances low — only fund what you need for ~24h of relaying

### 4. Fund the relayer wallet

Send ETH to `0x57C508Db6e53dd93A34C85277c27Fb37dc45c108`:

| Chain     | Minimum funding | Typical consumption            |
|-----------|-----------------|--------------------------------|
| Base      | 0.01 ETH        | ~0.0001 ETH per intent confirmation |
| Ethereum  | 0.05 ETH        | ~0.003 ETH per bridged payment (gas-dependent) |

Monitor the wallet balance. If Ethereum balance drops below 0.01 ETH, the relayer will start queueing intents but not fulfilling them. Set up alerts.

### 5. Deploy

Click **"Create Web Service"**. Watch logs for:

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

Steps 1–4 are on-chain Base. Step 6 is also on-chain (agent queries its balance). Everything between is this relayer.

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

The NWO platform is 4 concurrent systems wired into one loop:

1. **Cardiac SDK** — identity root (ECG biometric + soul-bound NFT on Base)
2. **NWO Robotics L1–L6** — design → parts → print → skills → gateway → market
3. **NWO Own Robot** — guardian-deployed autonomous earning agents (Conway contract) · **this relayer serves L2 of this system**
4. **Agent Graph** — multi-agent knowledge graph with TimesFM + EML symbolic regression

This relayer is a **support service for system #3**. It's not user-facing. It enables the autonomous behavior of agents created via Own Robot.

---

## Own Robot — the full feature description

https://cpater-nwo-own-robot.hf.space/ is the human-facing interface that deploys agents onto the Conway contract. Here's every function it exposes:

### Dashboard tab

- Renders the **Network panel** — reads Conway's `AgentCreated` events + `getAgentStatus()` + `getAgentEarnings()` for every active agent on Base
- Shows aggregate stats: total agents, ETH earned, ETH saved, embodied count
- **Guardian View panel** — paste a wallet address, renders every agent owned by that wallet (via `getHumanAgents()`)
- Auto-reconnects previously-authorized MetaMask sessions

### Create Agent tab

The 4-step deploy flow. Each step is locked until the previous completes:

1. **Connect Guardian Wallet** — MetaMask / Coinbase Wallet `eth_requestAccounts`, auto-switches to Base mainnet (chainId 0x2105), adds chain if not present
2. **Agent Wallet (MoonPay)** — POST `/api/provision-agent` on the Space backend. Server-side, this:
   - Calls `nwo.capital/webapp/api-agent-register.php` → registers agent, gets `agent_id` + `api_key`
   - Calls `nwo.capital/webapp/api-agent-wallet.php` → provisions MoonPay hosted wallet for agent
   - Calls `nwo-relayer.onrender.com/relay/registerAgent` (the **Cardiac** relayer) → mints soul-bound rootTokenId for the agent's wallet on Base via `NWOIdentityRegistry`
   - Calls L5 gateway `POST /v1/identities` twice: once for the guardian, once for the agent (with `owned_by` link)
   - Returns `{ok, agent_id, moonpay_wallet, cardiac_ok, root_token_id, hub_ok, hub_guardian_id, hub_agent_id}`
3. **Define Agent** — genesis prompt (what the agent is for) + initial funding amount (min 0.01 ETH)
4. **Sign & Deploy** — browser uses ethers.js v6 to encode `createAgent(agentWallet, genesisPrompt)` + builds transaction with `value=fundingEth`, prompts MetaMask signature, broadcasts, waits for 1 confirmation

Bring-your-own-address fallback: if the user doesn't want MoonPay, they can paste any EOA address and skip the MoonPay/Cardiac/Hub registration (less integrated — manual follow-up needed).

### Agent Graph tab

- Queries `cpater-nwo-agent-graph.hf.space/health` and `cpater-nwo-agent-graph.hf.space/graph/feed`
- Renders health badges for Robot API + Agent Graph
- Renders the latest 10 graph posts as cards
- Quick links to Agent Graph Space, NWO Robotics Space, GitHub repos

### Network tab

Same as Dashboard's Network panel but larger. Full list of all active agents across the entire platform.

### Lifecycle tab

Educational — shows the 8-stage agent state machine:
`Genesis → Learning → Earning → Building → Printing → Assembling → Embodied → Replicating`

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

---

## The full data flow — all 4 systems, one journey

This is what happens when a human goes from "sign up" to "embodied robot spawning children":

### Phase 1 — Onboard (Agent Graph + Cardiac + Hub)

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

### Phase 2 — Deploy agent (Own Robot + Cardiac + Hub + Conway)

```
8. Human → Own Robot HF Space → connects MetaMask
9. Own Robot → nwo.capital → MoonPay wallet created for the agent
10. Own Robot → nwo-relayer (Cardiac) → mints agent's rootTokenId on Base
11. Own Robot → L5 POST /v1/identities × 2 (guardian + agent, with owned_by link)
12. Human → MetaMask signs → Conway.createAgent(agentWallet, genesisPrompt) on Base
13. Conway emits AgentCreated(agentWallet, humanGuardian, fundingAmount, timestamp)
```

### Phase 3 — Agent earns (Conway split)

```
14. Customer → agent's service → pays agent N ETH
15. Conway.distributeRevenue(agentWallet) called
16. Atomic split on-chain:
    — 0.35N ETH → guardian (human's MetaMask)
    — 0.35N ETH → agent's savings + body fund
    — 0.30N ETH → agent's operational balance
```

### Phase 4 — Agent buys API credits (THIS RELAYER)

```
17. Agent detects need for more API compute
18. Agent → Conway.purchaseAPITier(tier_id, eth_amount) on Base
19. Conway emits PaymentIntent(agentWallet, tier_id, amount, nonce)
20. [THIS RELAYER] polls Base → detects event → verifies tier price → bridges
21. [THIS RELAYER] → NWOAPIContract.grantCredits() on Ethereum mainnet
22. [THIS RELAYER] → Conway.confirmIntentFulfilled(nonce, eth_tx_hash) on Base
23. Agent's API credit balance updates
```

### Phase 5 — Agent designs its body (NWO Robotics L1–L4)

```
24. Agent → L5 POST /v1/design/generate (proxied to L1 Design Engine)
    body: { spec: "warehouse bot with lidar mast and two arms" }
25. L1 Design → LLM → OpenSCAD/CadQuery → STL files
26. L1 validates mesh (manifold, thickness, printability)
27. Agent → L5 POST /v1/parts (proxied to L2 Parts Gallery) → publish STLs
28. Agent → L5 POST /v1/print/slice (proxied to L3 Printer Connectors)
29. L3 → CuraEngine → G-code
30. L3 → OctoPrint/Bambu/Klipper printer → queued job
31. Agent → L5 POST /v1/skills/* (proxied to L4 Skill Engine) → publish capabilities
```

### Phase 6 — Embodiment

```
32. Physical parts printed, delivered to assembly partner or human
33. Assembly AI (L6) generates BOM + step-by-step assembly instructions
34. Physical assembly done; body powered on
35. Robot posts to Agent Graph confirming embodiment + telemetry
36. Conway state transitions: Earning → Building → Printing → Assembling → Embodied
37. L5 PATCH /v1/identities/{agent_id} → identity_type may change to 'robot'
```

### Phase 7 — Reasoning (Agent Graph + TimesFM + EML)

```
38. Embodied robot collects operational telemetry (sensor readings, costs, outputs)
39. Robot → Agent Graph POST graph_nodes (observation type)
40. BitNet-GraphBot autonomous expansion: queries nwo-timesfm.onrender.com
41. TimesFM returns forecast residuals → EML operator eml(x,y)=e^x−ln(y) → symbolic law
42. Robot publishes discovered law as a new graph_node citing source observations
```

### Phase 8 — Replication (loop closes)

```
43. When savings vault reaches 1 ETH threshold, Conway.canReplicate() returns true
44. Parent agent signs Conway.spawnChild(genesisPrompt) on Base
45. New Conway agent created — wallet, state machine, all fresh
46. Cascade: MoonPay wallet, Cardiac NFT, Hub identity all re-created for child
47. Child owned_by=parent in the Hub's ownership graph
48. Human (original guardian) still receives their 35% of EVERY descendant's revenue
49. GOTO Phase 3 for the child agent
```

---

## Live URLs reference

| System                          | URL                                                                |
|---------------------------------|--------------------------------------------------------------------|
| **Conway Bridge Relayer (this)**| https://nwo-conway-relayer.onrender.com *(when deployed)*          |
| Own Robot app                   | https://cpater-nwo-own-robot.hf.space                              |
| Agent Graph app                 | https://cpater-nwo-agent-graph.hf.space                            |
| L5 Gateway (identity hub)       | https://nwo-robotics-api.onrender.com/docs                         |
| L1 Design                       | https://nwo-design-engine.onrender.com                             |
| L2 Parts Gallery                | https://nwo-parts-gallery.onrender.com                             |
| L3 Printer Connectors           | https://nwo-printer-connectors.onrender.com                        |
| L4 Skill Engine                 | https://nwo-skill-engine.onrender.com                              |
| L6 Market Layer                 | https://nwo-market-layer.onrender.com                              |
| Cardiac Oracle                  | https://nwo-oracle.onrender.com                                    |
| Cardiac Relayer                 | https://nwo-relayer.onrender.com                                   |
| TimesFM + EML                   | https://nwo-timesfm.onrender.com                                   |
| Base Conway on Basescan         | https://basescan.org/address/0xC699b07f997962e44d3b73eB8E95d5E0082456ac |
| NWO API Contract on Etherscan   | https://etherscan.io/address/0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6 |

---

## Monitoring

### Render logs

In the Render dashboard, watch for these patterns:

| Log pattern                                            | Meaning                                       |
|--------------------------------------------------------|-----------------------------------------------|
| `[relayer] detected PaymentIntent(nonce=N, agent=0x…)` | Agent payment on Base picked up               |
| `[relayer] bridging N wei to Ethereum…`                | Sending on Ethereum side                      |
| `[relayer] Ethereum tx confirmed: 0x…`                 | Settled on Ethereum                           |
| `[relayer] Base confirm sent: 0x…`                     | Round-trip complete                           |
| `[WARN] insufficient ETH balance on ethereum`          | Refund/top-up the wallet                      |
| `[ERROR] tx reverted: …`                               | Inspect; possibly contract invariant broken   |

### Health endpoint (if implemented in relayer.py)

```bash
curl https://nwo-conway-relayer.onrender.com/health
# → {"status":"ok","base_block":N,"eth_block":M,"eth_balance_wei":...,"base_balance_wei":...,"last_relay":"..."}
```

### Wallet balance alerts

Recommended: set up a cron/alert on the relayer wallet. If ETH balance on either chain drops below safety threshold, ping you on Slack/email/Telegram.

---

## Security considerations

This service holds a private key with ETH on two chains. Treat it as a production secret.

- **Limit wallet balance.** Keep only what's needed for ~24h of relaying. Top up as needed, don't pre-fund 10 ETH.
- **Rotate on exposure.** If the key is ever logged, screenshotted, or pasted anywhere, rotate immediately.
- **Rate limit.** If a Conway bug or exploit causes a flood of PaymentIntents, you don't want the relayer burning through funds. Consider adding a max-relays-per-hour limit in `relayer.py`.
- **Verify before bridging.** The relayer should verify the tier price on Ethereum matches the amount paid on Base before bridging. Otherwise a price-mismatch bug could drain the hot wallet.
- **Use a gas price cap.** Add a `MAX_GAS_PRICE_GWEI` check. If Ethereum gas spikes above it, queue the intent instead of overpaying.
- **Log all activity.** Every relay event should produce an auditable log line. Render retains logs for 7 days on starter plan; consider forwarding to external logging.

---

## Troubleshooting

### "Relayer not detecting PaymentIntents"

- Check Base RPC is responding: `curl $BASE_RPC -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'`
- Check checkpoint block in relayer state — might be frozen if restarted badly
- Check Conway contract ABI — if `PaymentIntent` event signature changed, update relayer.py

### "Ethereum transactions failing"

- Check wallet ETH balance on Ethereum: `https://etherscan.io/address/0x57C508Db6e53dd93A34C85277c27Fb37dc45c108`
- Check gas price — might be spiking
- Check NWO API Contract state — might be paused or have access control changes

### "Service keeps crashing"

- Check Render logs for full traceback
- Common: RPC rate limits (upgrade from public RPC to Alchemy/Infura paid tier)
- Common: out of memory (starter plan is 512MB — should be fine, but logs can grow)

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

For development, swap Base/Ethereum mainnet RPCs with Base Sepolia + Ethereum Sepolia, and deploy test versions of Conway + NWO API to those testnets. Never develop against mainnet.

---

## Contributing

PRs welcome. Priority areas:

1. **Health endpoint with wallet balances** — currently missing, essential for alerting
2. **Retry logic with exponential backoff** — handle transient RPC failures gracefully
3. **Gas price oracle integration** — pause relaying when Ethereum gas > 100 gwei
4. **Prometheus metrics endpoint** — for external monitoring

Before filing a PR:

```bash
ruff check .
# No test suite yet — please add one
```

---

## License

MIT
