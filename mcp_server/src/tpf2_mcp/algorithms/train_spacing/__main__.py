"""Offline evaluation: no native writer or running game required."""
import argparse
import json
from pathlib import Path

from .controller import TrainSpacingController


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', required=True, type=Path)
    parser.add_argument('--live', required=True, type=Path, help='Normalized rail-live JSON, not raw native positions')
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--now', type=float, help='Defaults to frame sampled_at for replay')
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
    network, live = read(args.network), read(args.live)
    controller = TrainSpacingController(network, read(args.policy) if args.policy else None)
    print(json.dumps(controller.step(live, now=args.now if args.now is not None else live['sampled_at']),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
