"""
AI Test Automation System - Entry Point
"""

import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load environment variables before constructing settings or graph services.
load_dotenv()

from src.config import settings
from src.api.dashboard import app
from src.graph.test_graph import test_automation_graph
from src.models.state import TestAutomationState
from src.utils.logger import configure_logging, get_logger

# Configure logging
configure_logging(settings.app.log_level)
logger = get_logger("main")


async def demo_run():
    """
    Demo execution with sample e-commerce application data.
    """
    logger.info("=" * 60)
    logger.info("AI TEST AUTOMATION SYSTEM")
    logger.info(f"Model: {settings.llm.model}")
    logger.info(f"LangSmith Project: {settings.langsmith.project}")
    logger.info(f"LangSmith tracing enabled: {bool(settings.langsmith.api_key and settings.langsmith.tracing_v2)}")
    if not settings.langsmith.api_key:
        logger.warning("LangSmith API key missing; set LANGCHAIN_API_KEY or LANGSMITH_API_KEY to enable tracing.")
    logger.info("=" * 60)
    
    # Sample inputs
    requirements = """
    User Story: E-commerce Checkout Flow
    AC1: User can add items to cart from product page
    AC2: Cart displays correct item count and total
    AC3: User can proceed to checkout
    AC4: Checkout form validates shipping address
    AC5: Payment processing accepts valid credit cards
    AC6: Order confirmation displays order number
    """
    
    source_code = {
        "src/pages/ProductPage.tsx": """
        export default function ProductPage() {
          const [cart, setCart] = useState([]);
          const addToCart = (product) => setCart([...cart, product]);
          return (
            <div data-testid="product-page">
              <button data-testid="add-to-cart" onClick={addToCart}>
                Add to Cart
              </button>
            </div>
          );
        }
        """,
        "src/pages/Cart.tsx": """
        export default function Cart() {
          const { items, total } = useCart();
          return (
            <div data-testid="cart-page">
              <span data-testid="item-count">{items.length}</span>
              <span data-testid="cart-total">${total}</span>
              <button data-testid="checkout-btn">Checkout</button>
            </div>
          );
        }
        """,
        "src/pages/Checkout.tsx": """
        export default function Checkout() {
          const [address, setAddress] = useState({});
          const validateAddress = () => address.zip && address.street;
          return (
            <form data-testid="checkout-form">
              <input data-testid="shipping-street" />
              <input data-testid="shipping-zip" />
              <button data-testid="place-order" disabled={!validateAddress()}>
                Place Order
              </button>
            </form>
          );
        }
        """,
        "src/api/payment.ts": """
        export async function processPayment(cardDetails: CardDetails) {
          const res = await fetch('/api/payment', {
            method: 'POST',
            body: JSON.stringify(cardDetails)
          });
          return res.json();
        }
        """,
    }
    
    api_docs = """
    openapi: 3.0.0
    info:
      title: E-commerce API
      version: 1.0.0
    paths:
      /api/cart/add:
        post:
          requestBody:
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    productId: { type: string }
                    quantity: { type: number }
          responses:
            200:
              description: Item added
      /api/payment:
        post:
          requestBody:
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    cardNumber: { type: string }
                    expiry: { type: string }
                    cvv: { type: string }
          responses:
            200:
              description: Payment processed
    """
    
    # Initialize state
    now_iso = datetime.now(timezone.utc).isoformat()
    now_tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    initial_state = TestAutomationState(
        requirements=requirements,
        source_code=source_code,
        api_docs=api_docs,
        test_plan="Focus on critical path: add to cart → checkout → payment",
        generated_tests=[],
        execution_results=[],
        failures=[],
        healed_tests=[],
        human_review_queue=[],
        explanation=None,
        current_step="init",
        iteration_count=0,
        max_iterations=settings.app.max_healing_iterations,
        trace_id=f"demo-{now_iso}",
        run_id=f"demo-{now_tag}",
        started_at=now_iso,
        completed_at=None,
        metrics={},
    )
    
    # Execute graph
    logger.info("starting_graph_execution", run_id=initial_state["run_id"])
    
    try:
        result = await test_automation_graph.ainvoke(initial_state)
        
        # Print results
        logger.info("=" * 60)
        logger.info("EXECUTION COMPLETE")
        logger.info("=" * 60)
        
        total = len(result["generated_tests"])
        passed = sum(1 for t in result["generated_tests"] if t["status"] == "passed")
        failed = sum(1 for t in result["generated_tests"] if t["status"] == "failed")
        healed = sum(1 for t in result["generated_tests"] if t["status"] == "healed")
        review = len(result["human_review_queue"])
        
        logger.info(f"Total Tests: {total}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Healed: {healed}")
        logger.info(f"Needs Review: {review}")
        
        if result.get("explanation"):
            logger.info("Report generated successfully")
            logger.info(f"Executive Summary: {result['explanation']['executive_summary'][:200]}...")
        
        return result
        
    except Exception as e:
        logger.error("graph_execution_failed", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    result = asyncio.run(demo_run())