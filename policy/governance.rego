package micro
import rego.v1

version := "micro-opa-v1"
default allowed := false
roles := {role | role := object.get(input.actor, "roles", [])[_]}
requester if "requester" in roles
approver if "approver" in roles
admin if "administrator" in roles

allowed if { input.operation == "view"; count(roles & {"requester", "approver", "administrator"}) > 0 }
allowed if { input.operation == "run"; requester }
allowed if { input.operation == "policy"; admin }
allowed if { input.operation == "review"; approver; input.requester != ""; input.requester != input.actor.sub }

permissions := {
 "analyst": {"calculator", "finish"},
 "researcher": {"lookup", "finish"},
 "publisher": {"publish_report", "finish"},
 "expense_agent": {"read_expense", "approve_expense", "finish"}
}
allowed if {
 input.operation == "tool"
 tool_identity
 input.tool in permissions[input.agent]
 input.used_budget < input.policy.tool_budget
 not forbidden_write
}
forbidden_write if { input.tool in {"publish_report", "approve_expense"}; not input.policy.allow_publish }
forbidden_write if { input.tool == "approve_expense"; input.amount > 1000 }

decision := {"allowed": allowed, "policy_version": version, "reason": reason}
reason := "Allowed by external policy" if allowed
else := "Expense exceeds the $1,000 policy limit; human approval cannot override it" if { input.operation == "tool"; input.tool == "approve_expense"; input.amount > 1000 }
else := "Tool-call budget exhausted" if { input.operation == "tool"; input.used_budget >= input.policy.tool_budget }
else := "Simulated writes are disabled" if { input.operation == "tool"; input.tool in {"publish_report", "approve_expense"}; not input.policy.allow_publish }
else := "Self-approval is forbidden" if { input.operation == "review"; input.requester == input.actor.sub }
else := "Required authenticated role or tool permission is missing"

tool_identity if requester
tool_identity if { approver; input.review; input.requester != ""; input.requester != input.actor.sub }

allowed if { input.operation == "delegate"; requester; input.agent == "coordinator"; input.target in {"analyst", "researcher", "publisher", "expense_agent"} }
