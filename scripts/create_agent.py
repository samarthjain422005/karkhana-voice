import json
import argparse
from pathlib import Path

from apps.api.bolna import BolnaClient
from apps.api.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ("close", "open", "alert")


def create_agent(agent_name: str, client: BolnaClient, public_base_url: str) -> str:
    agent_file = ROOT / "agents" / agent_name / "agent.json"
    prompt_file = ROOT / "agents" / agent_name / "prompt.md"
    spec = json.loads(agent_file.read_text(encoding="utf-8"))
    agent_config = spec["agent_config"]
    agent_config["webhook_url"] = f"{public_base_url.rstrip('/')}/webhooks/bolna"
    result = client.create_agent_v2(
        agent_config, prompt_file.read_text(encoding="utf-8").strip()
    )
    agent_id = result["agent_id"]
    print(f"Created Bolna {agent_name.title()} agent: {agent_id}")
    print(f"BOLNA_AGENT_ID_{agent_name.upper()}={agent_id}")
    return agent_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision Karkhana Voice agents in Bolna.")
    parser.add_argument(
        "--agent",
        choices=(*AGENTS, "all"),
        default="all",
        help="Create one agent or the complete three-agent workflow.",
    )
    args = parser.parse_args()
    settings = get_settings()
    if not settings.public_base_url.startswith("https://"):
        raise SystemExit("PUBLIC_BASE_URL must be a public HTTPS URL before creating an agent.")
    selected = AGENTS if args.agent == "all" else (args.agent,)
    client = BolnaClient()
    client.get_user_me()
    created: dict[str, str] = {}
    for agent_name in selected:
        created[agent_name] = create_agent(
            agent_name, client, settings.public_base_url
        )
    print("\nAdd these agent IDs to .env, then restart the API:")
    for agent_name, agent_id in created.items():
        print(f"BOLNA_AGENT_ID_{agent_name.upper()}={agent_id}")


if __name__ == "__main__":
    main()
