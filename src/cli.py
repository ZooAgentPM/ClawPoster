"""
visual-rag CLI: Search design assets with natural language.

Usage:
    python src/cli.py search "双十一大促海报，红色喜庆"
    python src/cli.py search "小红书美妆封面" --top 5
    python src/cli.py search "播客封面" --platform 小宇宙
    python src/cli.py index   # Pre-build embeddings for all assets
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import click
from search import search, format_result, build_embeddings, load_index

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_header():
    if HAS_RICH:
        console.print(Panel.fit(
            "[bold cyan]visual-rag[/bold cyan] [dim]— Design Asset Index for AI Agents[/dim]",
            border_style="cyan"
        ))
    else:
        print("=" * 50)
        print("  visual-rag — Design Asset Index for AI Agents")
        print("=" * 50)


@click.group()
def cli():
    """visual-rag: Search design assets with natural language."""
    pass


@cli.command()
@click.argument("query")
@click.option("--top", "-n", default=3, help="Number of results (default: 3)")
@click.option("--platform", "-p", default=None, help="Filter by platform, e.g. 小红书")
def search_cmd(query, top, platform):
    """Search design assets by natural language description."""
    print_header()

    if HAS_RICH:
        console.print(f"\n[bold]查询：[/bold] {query}")
        if platform:
            console.print(f"[bold]平台筛选：[/bold] {platform}")
        console.print()
    else:
        print(f"\n查询：{query}")
        if platform:
            print(f"平台筛选：{platform}")
        print()

    results = search(query, top_k=top, platform=platform)

    if not results:
        print("没有找到匹配的模板。")
        return

    for i, asset in enumerate(results, 1):
        output = format_result(asset, i)
        if HAS_RICH:
            score = asset["_score"]
            color = "green" if score > 0.5 else "yellow" if score > 0.2 else "red"
            console.print(Panel(
                output,
                border_style=color,
                expand=False
            ))
        else:
            print(output)
            print()


@cli.command()
@click.option("--force", is_flag=True, help="Rebuild all embeddings from scratch")
def index(force):
    """Pre-build embeddings for all assets in the index."""
    print_header()
    assets = load_index()
    print(f"\n正在为 {len(assets)} 个素材生成向量...\n")
    cache = build_embeddings(assets, force=force)
    hits = sum(1 for v in cache.values() if v is not None)
    print(f"\n完成！{hits}/{len(assets)} 个素材已生成向量，{len(assets)-hits} 个使用关键词搜索回退。")


@cli.command()
def list_assets():
    """List all assets in the index."""
    print_header()
    assets = load_index()
    print(f"\n共 {len(assets)} 个素材：\n")
    for a in assets:
        print(f"  [{a['id']}] {a['source']:10s} | {', '.join(a['use_cases'][:2])}")


# Allow: python src/cli.py search "..."
@click.pass_context
def main(ctx):
    pass


# Alias: `search` as default subcommand shortcut
cli.add_command(search_cmd, name="search")
cli.add_command(index, name="index")
cli.add_command(list_assets, name="list")

if __name__ == "__main__":
    # Shortcut: python cli.py "query" → runs search directly
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-") and sys.argv[1] not in ("search", "index", "list"):
        sys.argv.insert(1, "search")
    cli()
