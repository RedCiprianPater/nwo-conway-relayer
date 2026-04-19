"""
NWO Conway Bridge Relayer
Watches Base contract for payment intents and executes on Ethereum
"""

import os
import time
import json
from web3 import Web3
from eth_account import Account
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    # Base (source)
    "BASE_RPC": os.getenv("BASE_RPC", "https://mainnet.base.org"),
    "BASE_CONTRACT": "0xC699b07f997962e44d3b73eB8E95d5E0082456ac",  # Your deployed contract
    
    # Ethereum (destination)
    "ETH_RPC": os.getenv("ETH_RPC", "https://mainnet.infura.io/v3/YOUR_KEY"),
    "NWO_API_CONTRACT": "0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6",
    
    # Relayer wallet
    "RELAYER_KEY": os.getenv("RELAYER_KEY"),
}

class BridgeRelayer:
    def __init__(self):
        # Connect to Base
        self.base_w3 = Web3(Web3.HTTPProvider(CONFIG["BASE_RPC"]))
        
        # Connect to Ethereum
        self.eth_w3 = Web3(Web3.HTTPProvider(CONFIG["ETH_RPC"]))
        
        # Relayer account
        self.relayer = Account.from_key(CONFIG["RELAYER_KEY"])
        
        # Load Base contract
        self.base_contract = self.base_w3.eth.contract(
            address=CONFIG["BASE_CONTRACT"],
            abi=self._load_base_abi()
        )
        
        # Load NWO API contract
        self.nwo_contract = self.eth_w3.eth.contract(
            address=CONFIG["NWO_API_CONTRACT"],
            abi=self._load_nwo_abi()
        )
        
        logger.info(f"Relayer: {self.relayer.address}")
        logger.info(f"Base balance: {self.base_w3.from_wei(self.base_w3.eth.get_balance(self.relayer.address), 'ether')} ETH")
        logger.info(f"ETH balance: {self.eth_w3.from_wei(self.eth_w3.eth.get_balance(self.relayer.address), 'ether')} ETH")
    
    def _load_base_abi(self):
        return [
            {"inputs": [], "name": "getPendingIntents", "outputs": [{"name": "", "type": "bytes32[]"}], "stateMutability": "view", "type": "function"},
            {"inputs": [{"name": "intentId", "type": "bytes32"}], "name": "getPaymentIntent", "outputs": [{"components": [{"name": "intentId", "type": "bytes32"}, {"name": "agentWallet", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "tier", "type": "string"}, {"name": "timestamp", "type": "uint256"}, {"name": "executed", "type": "bool"}, {"name": "ethereumTxHash", "type": "bytes32"}], "name": "", "type": "tuple"}], "stateMutability": "view", "type": "function"},
            {"inputs": [{"name": "intentId", "type": "bytes32"}, {"name": "ethereumTxHash", "type": "bytes32"}], "name": "confirmPaymentExecuted", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"}
        ]
    
    def _load_nwo_abi(self):
        # You'll need the actual ABI from the NWO API contract
        return [
            {"inputs": [{"name": "agentAddress", "type": "address"}, {"name": "tier", "type": "string"}], "name": "purchaseTier", "outputs": [], "stateMutability": "payable", "type": "function"}
        ]
    
    def get_pending_intents(self):
        try:
            intents = self.base_contract.functions.getPendingIntents().call()
            logger.info(f"Pending intents: {len(intents)}")
            return intents
        except Exception as e:
            logger.error(f"Error getting intents: {e}")
            return []
    
    def get_intent_details(self, intent_id):
        try:
            intent = self.base_contract.functions.getPaymentIntent(intent_id).call()
            return {
                "intentId": intent[0],
                "agentWallet": intent[1],
                "amount": intent[2],
                "tier": intent[3],
                "timestamp": intent[4],
                "executed": intent[5],
                "ethereumTxHash": intent[6]
            }
        except Exception as e:
            logger.error(f"Error: {e}")
            return None
    
    def execute_on_ethereum(self, intent_details):
        try:
            agent_wallet = intent_details["agentWallet"]
            amount = intent_details["amount"]
            tier = intent_details["tier"]
            
            logger.info(f"Executing: {agent_wallet} | {self.eth_w3.from_wei(amount, 'ether')} ETH | {tier}")
            
            tx = self.nwo_contract.functions.purchaseTier(agent_wallet, tier).build_transaction({
                'from': self.relayer.address,
                'value': amount,
                'gas': 200000,
                'gasPrice': self.eth_w3.to_wei('20', 'gwei'),
                'nonce': self.eth_w3.eth.get_transaction_count(self.relayer.address)
            })
            
            signed_tx = self.eth_w3.eth.account.sign_transaction(tx, self.relayer.key)
            tx_hash = self.eth_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            logger.info(f"Sent: {tx_hash.hex()}")
            
            receipt = self.eth_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                logger.info(f"Confirmed: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Failed: {tx_hash.hex()}")
                return None
                
        except Exception as e:
            logger.error(f"Error: {e}")
            return None
    
    def confirm_on_base(self, intent_id, eth_tx_hash):
        try:
            tx = self.base_contract.functions.confirmPaymentExecuted(
                intent_id,
                self.base_w3.to_bytes(hexstr=eth_tx_hash)
            ).build_transaction({
                'from': self.relayer.address,
                'gas': 100000,
                'gasPrice': self.base_w3.to_wei('0.1', 'gwei'),
                'nonce': self.base_w3.eth.get_transaction_count(self.relayer.address)
            })
            
            signed_tx = self.base_w3.eth.account.sign_transaction(tx, self.relayer.key)
            tx_hash = self.base_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            logger.info(f"Confirm sent: {tx_hash.hex()}")
            
            receipt = self.base_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            
            if receipt['status'] == 1:
                logger.info("Confirmed on Base")
                return True
            else:
                logger.error("Confirm failed")
                return False
                
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
    
    def process_intent(self, intent_id):
        logger.info(f"Processing: {intent_id.hex()}")
        
        details = self.get_intent_details(intent_id)
        if not details:
            return False
        
        if details["executed"]:
            logger.info("Already executed")
            return True
        
        eth_tx_hash = self.execute_on_ethereum(details)
        if not eth_tx_hash:
            return False
        
        success = self.confirm_on_base(intent_id, eth_tx_hash)
        if not success:
            return False
        
        logger.info(f"Success: {intent_id.hex()}")
        return True
    
    def run(self):
        logger.info("🌉 Bridge Relayer started")
        
        while True:
            try:
                intents = self.get_pending_intents()
                
                if len(intents) == 0:
                    logger.info("No intents, sleeping...")
                    time.sleep(30)
                    continue
                
                for intent_id in intents:
                    self.process_intent(intent_id)
                    time.sleep(5)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    relayer = BridgeRelayer()
    relayer.run()