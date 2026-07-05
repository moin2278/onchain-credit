"""Ground-truth backtest pipeline.

Tests the core hypothesis: wallets scored HIGH risk by api/scoring.py
get liquidated at a materially higher rate than wallets scored LOW.

Pipeline:
  1. pull_events.py    - pull liquidation + borrow events from Etherscan logs
  2. build_dataset.py  - point-in-time features per wallet (30d pre-event)
  3. run_backtest.py   - tier x outcome table, capture rate, lift, chart

Event topic0 hashes below were computed with keccak-256 from the canonical
ABI signatures (generator: scripts in this package; keccak implementation
verified against the known Transfer(address,address,uint256) vector).
"""

# Aave V3 Pool (Ethereum mainnet)
AAVE_V3_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"

# LiquidationCall(address indexed collateralAsset, address indexed debtAsset,
#                 address indexed user, uint256 debtToCover,
#                 uint256 liquidatedCollateralAmount, address liquidator,
#                 bool receiveAToken)
# borrower = topics[3]
AAVE_V3_LIQUIDATION_TOPIC0 = (
    "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286"
)

# Borrow(address indexed reserve, address user, address indexed onBehalfOf,
#        uint256 amount, uint8 interestRateMode, uint256 borrowRate,
#        uint16 indexed referralCode)
# borrower = topics[2] (onBehalfOf)
AAVE_V3_BORROW_TOPIC0 = (
    "0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0"
)

EVENT_CONFIGS = {
    "aave_v3": {
        "chain_id": 1,
        "pool": AAVE_V3_POOL,
        "liquidation_topic0": AAVE_V3_LIQUIDATION_TOPIC0,
        "liquidation_borrower_topic_index": 3,
        "borrow_topic0": AAVE_V3_BORROW_TOPIC0,
        "borrow_borrower_topic_index": 2,
    },
    # Morpho Blue support is scaffolded but EXPERIMENTAL - verify the
    # singleton address + event layout onchain before relying on results.
    # Liquidate(bytes32 indexed id, address indexed caller,
    #           address indexed borrower, ...)  -> borrower = topics[3]
    # topic0: 0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41
}


def topic_to_address(topic: str) -> str:
    """Convert a 32-byte topic hex to a 0x address (last 20 bytes)."""
    t = topic.lower().replace("0x", "")
    return "0x" + t[-40:]
