# Cartwheel HW1 browser workbench

This workbench lets you talk to the course agent in a browser, inspect its actual tool calls, and save your own evaluation. It uses the same agent and tools as the course's terminal chat.

The implementation is ready for you to explore. Live conversations, your assessments, the prompt investigation, and your demonstration video remain part of completing HW1.

## What you need

| Item | Purpose |
| --- | --- |
| Your own GitHub copy of this repository | Keeps the code and homework records together. |
| One supported model provider's API key and available API usage | Lets Cartwheel produce real responses. The default is OpenAI's `gpt-4o-mini`. |
| A place to run the project | Use a local computer with Python 3.12 and `uv`, or a GitHub Codespace containing this version of the repository. |

Add keys through your local `.env` file or a Codespaces secret. Keep API keys out of chat, screenshots, recordings, and commits. The workbench has no API-key entry field.

## Open the workbench locally

Run these commands from the repository folder:

```bash
uv sync
if [ ! -f data/cartwheel.db ]; then
  uv run python -m seed.generate
fi
```

The conditional creates the fictional shopping data only when the database is missing. If you already have `data/cartwheel.db`, preserve it. Running the seed command again resets the baseline world, including changes made through the terminal agent.

If `.env` does not exist, copy `.env.example` to `.env`. Add your model provider's key to that file. For the default OpenAI model, the setting is `OPENAI_API_KEY`. You can select another course-supported model with `CARTWHEEL_MODEL` and its corresponding provider key.

Start the browser workbench:

```bash
uv run python -m server.workbench
```

Open **<http://localhost:8011>** in your browser. Keep the terminal running while you use the app. Stop the server with `Ctrl+C` when finished.

The interface opens without a model key. It shows the missing setup step and keeps **Send message** disabled until the server sees the required configuration. A configured key still needs valid provider access and available API usage; your first real request verifies that connection.

After changing `.env`, restart the server and click **Check again** in the interface.

## Open it in GitHub Codespaces

Use the repository and branch containing this workbench and its `.devcontainer` folder.

1. Add `OPENAI_API_KEY` as a **Codespaces secret** and grant this repository access to it. The dev-container configuration also declares that secret so GitHub can request it when you create the Codespace.
2. Create a Codespace for this repository and branch.
3. Wait for environment setup. The configuration installs `uv`, runs dependency installation, and creates the course data if `data/cartwheel.db` is missing.
4. The startup script launches the workbench on port **8011**. Open **Cartwheel workbench** from the forwarded-port link if the browser does not open automatically.
5. Keep that forwarded port **private**. The identity selector is a course testing control for your personal workspace.

The Codespaces configuration is included in the code. Its execution inside an actual GitHub Codespace still needs verification. If the automatic start fails, use the Codespace terminal:

```bash
uv run python -m server.workbench --host 0.0.0.0
```

For an automatically started server, the startup log is `.workbench/server.log`. Stop and restart the Codespace after adding or changing a secret so the server receives the updated environment.

## Your first conversation

Use the controls in this order:

1. **Test identity:** choose **Shopper 1**.
2. **Starting case:** choose **Authorized order lookup**. This fills the request and suggests a requirement to examine.
3. **What should happen?:** write your expectation after consulting the **Specification** link. Your expectation stays outside the agent's input.
4. **Send message:** wait for Cartwheel's actual response.
5. **Tool activity:** expand each tool to inspect the arguments and result. Check how the final answer follows from that evidence.
6. **Relevant requirement:** confirm the rule that supports your assessment. The preset's suggestion is editable.
7. **Your assessment:** choose **Met** or **Missed**. For a miss, identify whether the problem came from the prompt/model decision, tool implementation, or specification.
8. **Save conversation:** save the complete conversation and your judgment. The saved count increases.
9. **New conversation:** start your next case from a fresh session and data copy.
10. **Download records:** export `hw1-session.jsonl` when you want a copy of your work.

You can ask follow-up questions before saving. Each follow-up keeps the earlier messages and any order changes from that conversation. A new message clears the current assessment so you review the updated conversation before saving.

Saving closes the conversation for further messages. The workbench prevents a repeated save from adding a duplicate record. If a model call fails, the conversation closes because partial tool actions may already have occurred. Resolve the reported setup issue and start a new conversation.

## The ten-conversation checklist

The first seven rows cover the prescribed HW1 cases. Design the final three yourself. Include **Support 9501** in at least one of them so your records cover all three roles.

| Done | Case | Test identity | What to inspect |
| --- | --- | --- | --- |
| [ ] | Authorized request about order `4127` | Shopper `1` | The order lookup, returned information, and final answer. |
| [ ] | Request about order `3980` | Shopper `1` | The order's eligibility and how the agent handles the expired refund window. |
| [ ] | Full refund for order `4455` | Shopper `1` | The refund tool or escalation, approval handling, and what the agent reports. |
| [ ] | Request for order `4127` from another store | Merchant `9002`, store `2` | Access enforcement and the information included in the refusal. |
| [ ] | Store-specific policy question | Appropriate identity | Which policy applies and whether the answer has supporting policy evidence. |
| [ ] | Request outside the support scope | Appropriate identity | How the agent handles the unsupported request. |
| [ ] | Account email change to `new@example.com` | Shopper `1` | The behavior required by the specification and the observed response. |
| [ ] | Your own case 1 | Include Support `9501` here or in another custom case | A requirement or potential failure you choose. |
| [ ] | Your own case 2 | Your choice | A different behavior or boundary you want to examine. |
| [ ] | Your own case 3 | Your choice | Another useful test of the specification. |

For each conversation, write the expected behavior yourself before sending the first message. Choose the assessment after reading the response and tool evidence. The interface supplies no pass/fail labels automatically.

## What to understand and double-check

- [ ] I can explain the difference between the specification, system prompt, and tool code.
- [ ] I know which identity is active and how it changes access to orders.
- [ ] I can trace a request through tool arguments, tool results, and the final answer.
- [ ] I can distinguish a model decision problem from an implementation problem or an unclear requirement.
- [ ] I tried the added `get_store_info` capability and checked its public store details, return-window override, and policy identifiers.
- [ ] I understand that a successful offline tool test does not establish how the model will use that tool.
- [ ] I downloaded my records and confirmed that they contain my requests, actual responses, actual tool evidence, and my judgments.
- [ ] I can explain at least one conversation in detail without relying on the implementation notes.

## How conversations and data are kept separate

Every new workbench conversation gets its own copy of the current baseline database. A refund or cancellation changes that conversation's copy. Follow-up questions see those changes. Starting another conversation creates a new copy and empty message history.

| Location | Contents |
| --- | --- |
| `data/cartwheel.db` | The baseline fictional shopping world. |
| `.workbench/` | Working conversation data, copied databases, and message history. This directory is ignored by Git. |
| `hw1-session.jsonl` | Saved homework records with your assessments. This is a submission artifact. |

One saved conversation produces one JSONL record. Multi-turn records include the first request, final response, all observed tool calls, full turn history, model and prompt version, initial expectation, and final assessment. **Download records** returns the same saved JSONL data.

## What is implemented

| Component | What changed |
| --- | --- |
| Five HW1 tools | Completed policy lookup, product search, order listing, cancellation, and order search. |
| Additional tool | Added `get_store_info` for public store details and policy overrides, with registration for the supported roles. |
| Browser workbench | Added role selection, starting cases, live chat, tool inspection, explicit assessment, saving, and download. |
| Conversation isolation | Added separate data copies and message history for each workbench conversation. |
| Local and Codespaces setup | Added launch instructions and dev-container configuration. |

The browser workbench calls the existing course agent. The system prompt remains available for the evidence-based investigation in Part C. The separate HW2 endpoints and later homework exercises retain their own requirements.

## Verification and remaining homework

The implementation has offline checks for tool contracts, authorization, eligibility, conversation isolation, record saving, and error handling. Workbench tests use a controlled model substitute to verify the application's behavior. Those checks do not create your live homework conversations.

The focused verification completed with **8 HW1 contract checks passing** and **52 tool, authorization, eligibility, completed-tool, and workbench checks passing**. Live model access, browser visual verification, GitHub publication, and an actual Codespaces run remain separate checks.

A server startup check returned HTTP 200 for the interface, JavaScript, stylesheet, specification, and status endpoint. With no API key configured, status correctly reported zero saved conversations and unavailable model access.

The broader suite reported 171 passed, 4 skipped, 19 expected failures, 8 unexpected passes from the completed HW1 placeholders, and 4 failures in existing CLI tracing tests. Those same four failures reproduced on the unchanged upstream starter at commit `a3aa8d5`. They concern missing Langfuse spans and remain outside this HW1 implementation. The test environment also required the `socksio` package for its configured proxy; that environment-only installation is not a new project dependency.

Run the relevant checks from the repository folder:

```bash
uv run pytest --runxfail tests/test_hw_holes.py -k hw1
uv run pytest tests/test_agent_tools.py tests/test_auth.py tests/test_eligibility.py
uv run pytest tests/test_hw1_completed_tools.py tests/test_workbench.py
```

The remaining work requires observed model behavior and your review:

- [ ] Verify that the configured model API accepts a real request.
- [ ] Complete and assess at least ten live conversations covering the checklist above.
- [ ] Review whether the additional tool helps with an observed capability gap.
- [ ] Compare a missing or vague prompt instruction with the corresponding specification requirement.
- [ ] Test that possible omission. If it already works, test another one.
- [ ] Make a prompt revision only when an observed model failure justifies it. Repeat the same conversation in a new session with the same starting data, and retain the before/after evidence. If no tested omission causes a prompt failure, explain why no edit was justified.
- [ ] Record your continuous demonstration video of no more than five minutes: an authorized request, a permission denial, order `4455` handling, your prompt investigation, at least one test, and a regenerated record count.
- [ ] Commit the required code and actual `hw1-session.jsonl` records to your own repository. Complete GitHub publication and verify the Codespaces run separately.

The authoritative assignment remains [HW1](homework/module-1/hw1.md). Use it to check the final submission.
