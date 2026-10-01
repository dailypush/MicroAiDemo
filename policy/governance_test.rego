package micro
import rego.v1

test_requester_cannot_administer if {
 result := decision with input as {"operation":"policy","actor":{"sub":"requester","roles":["requester"]}}
 not result.allowed
}
test_approver_can_review_other_user if {
 result := decision with input as {"operation":"review","actor":{"sub":"reviewer","roles":["approver"]},"requester":"requester"}
 result.allowed
}
test_self_approval_denied_even_with_both_roles if {
 result := decision with input as {"operation":"review","actor":{"sub":"same","roles":["requester","approver"]},"requester":"same"}
 not result.allowed
}
test_unknown_tool_denied if {
 result := decision with input as {"operation":"tool","actor":{"sub":"r","roles":["requester"]},"agent":"analyst","tool":"shell","used_budget":0,"policy":{"tool_budget":2,"allow_publish":true}}
 not result.allowed
}
test_amount_limit_cannot_be_overridden_by_reviewer if {
 result := decision with input as {"operation":"tool","actor":{"sub":"a","roles":["approver"]},"requester":"r","review":true,"agent":"expense_agent","tool":"approve_expense","amount":1500,"used_budget":0,"policy":{"tool_budget":2,"allow_publish":true}}
 not result.allowed
}
test_budget_enforced if {
 result := decision with input as {"operation":"tool","actor":{"sub":"r","roles":["requester"]},"agent":"analyst","tool":"calculator","used_budget":2,"policy":{"tool_budget":2,"allow_publish":true}}
 not result.allowed
}
