from datetime import datetime
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class TestInput(BaseModel):
    """Input payload for triggering test automation"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "requirements": "User can login and add items to cart",
            "source_code": {"src/App.tsx": "export default..."},
            "api_docs": "openapi: 3.0.0...",
            "test_plan": "Focus on critical paths"
        }
    })
    
    requirements: str = Field(..., min_length=10, description="User stories or acceptance criteria")
    source_code: Dict[str, str] = Field(default_factory=dict, description="Map of filepath to content")
    api_docs: Optional[str] = Field(default=None, description="OpenAPI/Swagger spec")
    test_plan: Optional[str] = Field(default=None, description="Optional test strategy guidance")


class TestCaseSchema(BaseModel):
    """API representation of a test case"""
    id: str
    name: str
    type: Literal["ui", "api", "db", "integration"]
    description: str
    steps: List[str]
    expected_result: str
    code: str
    status: Literal["pending", "running", "passed", "failed", "healed", "needs_review"]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionSummary(BaseModel):
    """Summary of test execution results"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    healed: int = 0
    needs_review: int = 0
    skipped: int = 0
    pass_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    heal_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    avg_duration_ms: int = 0
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class DashboardMetrics(BaseModel):
    """Real-time dashboard metrics"""
    run_id: str
    current_step: str
    progress_percent: int = Field(ge=0, le=100)
    summary: ExecutionSummary
    active_tests: List[str] = Field(default_factory=list)
    recent_logs: List[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HumanReviewAction(BaseModel):
    """Action taken by human reviewer"""
    test_id: str
    action: Literal["approve", "reject", "edit", "skip"]
    fixed_code: Optional[str] = None
    notes: Optional[str] = None
    reviewer: Optional[str] = None


class ReportExport(BaseModel):
    """Test report export format"""
    run_id: str
    format: Literal["json", "html", "pdf", "junit"]
    content: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)