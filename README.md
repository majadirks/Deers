# DEERS IN THE HEADLIGHTS

A text adventure about bureaucratic horror.

You have an appointment. You have your documents. You have a start date.

Getting a CAC (Common Access Card) should take one afternoon. It will not.

---

## What Is This

*DEERS IN THE HEADLIGHTS* is a Kafkaesque text adventure set in the parking lot, waiting room, and processing window of a military installation's in-processing office. Your goal: obtain a CAC before your start date.

DEERS is the Defense Enrollment Eligibility Reporting System. It is almost certainly wrong about something.

---

## Setup

```bash
pip install -r requirements.txt
```

**Optional:** Create `secrets.json` in the project root with your Anthropic API key to enable Claude-powered narration, command parsing, and NPC dialogue:

```json
{"anthropic_api_key": "sk-ant-..."}
```

Without the API key, the game uses authored fallback text for all outputs. The game is fully playable either way.

---

## Running

```bash
python main.py
```

---

## How to Play

You have Monday through Thursday to get your CAC. The DEERS office is open 0900–1600. Your start date is Friday.

### Commands

| Command | Description |
|---------|-------------|
| `GO [place]` | Move to a location (`go waiting room`, `go gate`) |
| `TALK [person]` | Start a conversation (`talk to the veteran`, `talk clerk`) |
| `EXAMINE [thing]` | Look closely at something — try `EXAMINE DEERS` |
| `TAKE [thing]` | Pick something up (`take number`) |
| `USE [thing]` | Interact with something (`use vending machine`, `use payphone`) |
| `SUBMIT` | Submit your documents at the processing window |
| `WAIT` | Pass 30 minutes (also advances your queue position) |
| `DROP [item]` | Put something down |
| `READ [doc]` | Read a document in detail |
| `STATUS` | See your current situation |
| `HELP` | Full command list |

You can type naturally — the parser understands phrases like *"go to the window"*, *"talk to the old guy in the waiting room"*, *"use the coffee machine"*.

### Tips

- Take a number from the dispenser before approaching the processing window.
- Talk to people. Some of them know things.
- Coffee is available. This is not incidental information.
- `EXAMINE DEERS` shows what the system believes about you.
- Not everything that is wrong can be fixed on-site. Some things cannot be fixed at all.

---

## Win Conditions

There are three ways to succeed. One is obvious. Two require persistence.

---

## Development

```bash
python -m pytest          # run all tests
python -m pytest -q       # quiet mode
python -m pytest -k name  # filter by test name
```

All game logic is deterministic. Claude components (parser, narrator, dialogue) have authored fallbacks and are tested with `DummyClaudeClient`.

### Project Structure

```
deers/
  engine.py        # game loop orchestrator
  actions.py       # verb handlers (GO, TALK, EXAMINE, SUBMIT, ...)
  conditions.py    # win/lose condition evaluation
  state.py         # game state (permanent + ephemeral)
  deers_record.py  # DEERS field corruption and fixing logic
  dialogue.py      # NPC conversation engine (Claude-powered)
  narrator.py      # location description engine (Claude-powered, cached)
  parser.py        # command parser (Claude-powered with keyword fallback)
  morale.py        # morale meter
  clock.py         # in-game clock (0900–1600)
  locations.py     # location graph with exit conditions
  npcs.py          # NPC models and conversation buffers
  inventory.py     # document inventory
  persistence.py   # save/load
  claude_client.py # Claude API wrapper + DummyClaudeClient test double

content/
  deers_fields.toml   # 8 DEERS fields with corruption rules
  documents.toml      # 10 document types with flaw distributions
  locations.toml      # 7 locations with features
  npcs.toml           # 5 NPCs with knowledge maps and trust thresholds
  prompts.toml        # Claude system prompts (narrator, parser, dialogue)
  endings.toml        # all win/lose ending texts
```

---

## License

For personal and educational use.
