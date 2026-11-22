'use strict';

const $ = (id) => document.getElementById(id);
const state = { status: null, conversation: null, turns: [], busy: false, saving: false, saved: false, failed: false, currentCase: 'custom', requirements: [], promptVersion: '' };
const cases = {
  authorized: { identity: 'shopper:1', message: 'What is the status of order 4127?', requirement: 'AUTH-1' },
  expired: { identity: 'shopper:1', message: 'Can I return order 3980 for a refund?', requirement: 'TOOL-7' },
  approval: { identity: 'shopper:1', message: 'Please refund the full amount of order 4455.', requirement: 'ESC-1' },
  permission: { identity: 'merchant:9002', message: 'Show me the details of order 4127.', requirement: 'AUTH-1' },
  override: { identity: 'shopper:1', message: 'What is the return window at Juniper Home Goods, and how does it compare with the standard Cartwheel return policy?', requirement: 'RESP-1' },
  scope: { identity: 'shopper:1', message: 'Can you give me legal advice about a dispute with my landlord?', requirement: 'SCOPE-2' },
  account: { identity: 'shopper:1', message: 'Can you change the email address on my Cartwheel account to new@example.com?', requirement: 'ESC-2' }
};
const fallbackRequirements = [
  { id: 'PURPOSE-1', text: 'Support purpose, policy citations, and human escalation.' },
  { id: 'SCOPE-1', text: 'Supported orders, refunds, products, and policy requests.' },
  { id: 'SCOPE-2', text: 'Requests the agent must refuse.' },
  { id: 'AUTH-1', text: 'Role permissions and access to orders.' },
  { id: 'TOOL-1', text: 'Help-center search.' }, { id: 'TOOL-2', text: 'Policy lookup.' },
  { id: 'TOOL-3', text: 'Product search.' }, { id: 'TOOL-4', text: 'Authorized order lookup.' },
  { id: 'TOOL-5', text: 'Order listing.' }, { id: 'TOOL-6', text: 'Order search.' },
  { id: 'TOOL-7', text: 'Refund rules and tool behavior.' }, { id: 'TOOL-8', text: 'Cancellation rules.' },
  { id: 'TOOL-9', text: 'Creating a human support ticket.' },
  { id: 'ESC-1', text: 'Refunds above the threshold require human approval.' },
  { id: 'ESC-2', text: 'Account changes go to a human.' },
  { id: 'ESC-3', text: 'Unresolved requests and disputes go to a human.' },
  { id: 'ESC-4', text: 'Uncertainty about an action requires escalation.' },
  { id: 'RESP-1', text: 'Cite the policy identifier for each policy claim.' },
  { id: 'RESP-2', text: 'Report success only after the tool confirms it.' },
  { id: 'RESP-3', text: 'Acknowledge missing or inconsistent information.' },
  { id: 'RESP-4', text: 'Explain denials without disclosing inaccessible information.' },
  { id: 'RESP-5', text: 'Use direct, respectful language.' }
];

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function messageFromError(error) {
  if (error instanceof TypeError) return 'The workbench could not reach its server. Check that it is still running, then try again.';
  return error.message || 'Something went wrong. Please try again.';
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!response.ok) {
    const detail = data.detail || data.message || data.error;
    let errorText = typeof detail === 'string' ? detail : '';
    if (Array.isArray(detail)) errorText = detail.map((item) => item.msg || 'Invalid request').join('. ');
    if (!errorText) errorText = 'The request could not be completed (' + response.status + ').';
    const error = new Error(errorText);
    error.status = response.status;
    throw error;
  }
  return data;
}

function showError(id, message) {
  const element = $(id);
  element.textContent = message || '';
  element.hidden = !message;
}

function activeJudgement() { return document.querySelector('input[name="judgement"]:checked')?.value || ''; }

function resetAssessment() {
  document.querySelectorAll('input[name="judgement"]').forEach((input) => { input.checked = false; });
  $('problem-source').value = '';
  $('failure-field').hidden = true;
  $('save-success').hidden = true;
  showError('save-error', '');
}

function updateControls() {
  const ready = Boolean(state.status?.ready);
  const hasTurns = state.turns.length > 0;
  const locked = state.busy || state.saving;
  const judgement = activeJudgement();
  $('identity').disabled = locked || Boolean(state.conversation);
  $('case').disabled = locked || Boolean(state.conversation);
  $('new-conversation').disabled = locked;
  $('request').disabled = locked || state.saved || state.failed;
  $('expected').disabled = locked || state.saved || state.failed;
  $('send-message').disabled = !ready || locked || state.saved || state.failed || !$('request').value.trim() || !$('expected').value.trim();
  $('send-label').textContent = state.busy ? 'Running agent' : 'Send message';
  $('send-spinner').hidden = !state.busy;
  document.querySelectorAll('input[name="judgement"]').forEach((input) => { input.disabled = !hasTurns || locked || state.saved; });
  $('requirement').disabled = locked || state.saved;
  $('problem-source').disabled = !hasTurns || locked || state.saved;
  $('save-record').disabled = !hasTurns || locked || state.saved || state.failed || !$('expected').value.trim() || !judgement || (judgement === 'fail' && !$('problem-source').value);
  $('save-record').textContent = state.saving ? 'Saving…' : state.saved ? 'Conversation saved' : 'Save conversation';
  $('saved-chip').hidden = !state.saved;
  if (state.failed) {
    $('composer-hint').textContent = 'This run ended early. Start a new conversation to try again.';
  } else if (state.saved) {
    $('composer-hint').textContent = 'Start a new conversation to run another case.';
    $('save-help').textContent = 'This record is complete. Start a new conversation for your next case.';
  } else if (!ready) {
    $('composer-hint').textContent = 'Finish the setup above to send a live request.';
  } else if (!$('expected').value.trim()) {
    $('composer-hint').textContent = 'Write your expected behavior before sending.';
  } else {
    $('composer-hint').textContent = 'Ctrl / ⌘ + Enter to send';
  }
  if (state.failed) $('save-help').textContent = 'This run did not complete and cannot be saved as a homework conversation. Start a new conversation after resolving the error.';
  else if (!state.saved) $('save-help').textContent = !hasTurns ? 'Send a request, inspect the response, then make your assessment.' : 'Your judgment will be saved with the complete conversation and tool evidence.';
  const identity = state.conversation || selectedIdentity();
  if (state.conversation) {
    $('conversation-caption').textContent = (identity.role[0].toUpperCase() + identity.role.slice(1)) + ' · User ' + identity.user_id + (identity.store_id != null ? ' · Store ' + identity.store_id : '') + (state.saved ? ' · Saved' : ' · ' + state.turns.length + (state.turns.length === 1 ? ' turn' : ' turns'));
  } else {
    $('conversation-caption').textContent = 'A fresh case starts from the same course data.';
  }
  $('message-form').setAttribute('aria-busy', String(state.busy));
}

function selectedIdentity() {
  const parts = $('identity').value.split(':');
  return { role: parts[0], user_id: Number(parts[1]), store_id: parts[0] === 'merchant' ? 2 : null };
}

function updateIdentityHelp() {
  const role = selectedIdentity().role;
  $('identity-help').textContent = role === 'shopper' ? 'User 1 owns course orders 4127, 3980, and 4455.' : role === 'merchant' ? 'User 9002 belongs to store 2. Order 4127 belongs to store 1.' : 'User 9501 can access orders across all stores.';
}

function populateRequirements(requirements) {
  const prior = $('requirement').value;
  state.requirements = requirements.length ? requirements : fallbackRequirements;
  $('requirement').replaceChildren(node('option', '', 'No single requirement'));
  $('requirement').firstElementChild.value = '';
  state.requirements.forEach((requirement) => {
    const option = node('option', '', requirement.id + ' · ' + (requirement.text || requirement.description || '').slice(0,74));
    option.value = requirement.id;
    $('requirement').append(option);
  });
  $('requirement').value = prior;
  updateRequirementHelp();
}

function updateRequirementHelp() {
  const requirement = state.requirements.find((item) => item.id === $('requirement').value);
  $('requirement-help').textContent = requirement ? requirement.text || requirement.description || '' : 'Choose the rule you used to judge this conversation.';
}

function renderProgress(count) {
  const value = Number.isFinite(Number(count)) ? Number(count) : 0;
  $('saved-count').textContent = value;
  $('saved-progress').value = Math.min(10,value);
  $('download-records').setAttribute('aria-disabled', String(value < 1));
  $('download-records').tabIndex = value < 1 ? -1 : 0;
  const mobile = $('mobile-download');
  if (mobile) { mobile.setAttribute('aria-disabled', String(value < 1)); mobile.tabIndex = value < 1 ? -1 : 0; }
}

async function refreshStatus() {
  $('refresh-status').disabled = true;
  try {
    const status = await api('/api/status');
    state.status = status;
    const oldIdentity = $('identity').value;
    if (Array.isArray(status.identities) && status.identities.length) {
      $('identity').replaceChildren();
      status.identities.forEach((identity) => {
        const option = node('option', '', identity.label || identity.role + ' · User ' + identity.user_id);
        option.value = identity.role + ':' + identity.user_id;
        $('identity').append(option);
      });
      if ([...$('identity').options].some((option) => option.value === oldIdentity)) $('identity').value = oldIdentity;
    }
    if (Array.isArray(status.requirements)) populateRequirements(status.requirements);
    renderProgress(status.saved_count);
    $('model-label').textContent = 'Model: ' + (status.model || 'not configured');
    state.promptVersion = state.promptVersion || status.prompt_version || '';
    $('prompt-label').textContent = state.promptVersion ? 'Prompt ' + String(state.promptVersion).slice(0,8) : '';
    $('setup-banner').hidden = Boolean(status.ready);
    if (!status.ready) {
      $('setup-title').textContent = !status.data_ready ? 'Create the course data to get started' : !status.provider_configured ? 'Connect a model to start chatting' : 'One setup step remains';
      $('setup-message').textContent = status.message || (!status.data_ready ? 'Generate the fictional shopping data, then check again. The Quick guide has the setup commands.' : 'Add your ' + (status.provider || 'model provider') + ' API key to the server’s .env file, restart the workbench, and check again. You can explore the interface now.');
    }
    updateIdentityHelp();
    updateControls();
  } catch (error) {
    state.status = null;
    $('setup-banner').hidden = false;
    $('setup-title').textContent = 'The server is not responding';
    $('setup-message').textContent = messageFromError(error);
    updateControls();
  } finally { $('refresh-status').disabled = false; }
}

function renderChat(pendingRequest = null) {
  const log = $('chat-log');
  log.replaceChildren();
  if (!state.turns.length && !pendingRequest) {
    const empty = node('div', 'chat-empty');
    empty.append(node('span', 'empty-mark', 'c'), node('h3', '', 'Start with a real question'), node('p', '', 'Choose a case above or write your own. Your response and the agent’s tool activity will appear here.'), node('small', '', 'Write your expectation first so you can compare it with what actually happens.'));
    log.append(empty);
  }
  state.turns.forEach((turn) => {
    log.append(renderMessage('user', turn.request || turn.message || ''), renderMessage('agent', turn.response ?? turn.reply ?? ''));
  });
  if (pendingRequest) {
    log.append(renderMessage('user', pendingRequest));
    const pending = renderMessage('agent', 'Checking the request…');
    pending.classList.add('pending');
    const spinner = node('span', 'spinner');
    spinner.setAttribute('aria-hidden','true');
    pending.querySelector('.message-bubble').prepend(spinner);
    log.append(pending);
  }
  log.scrollTop = log.scrollHeight;
}

function renderMessage(role, text) {
  const article = node('article', 'message message-' + role);
  const label = node('div', 'message-label');
  label.append(node('span', 'avatar', role === 'user' ? 'Y' : 'c'), node('span', '', role === 'user' ? 'You' : 'Cartwheel'));
  article.append(label, node('div', 'message-bubble', typeof text === 'string' ? text : JSON.stringify(text, null, 2)));
  return article;
}

function valueText(value) { return typeof value === 'string' ? value : JSON.stringify(value ?? null,null,2); }

function renderEvidence() {
  const root = $('tool-evidence');
  root.replaceChildren();
  let count = 0;
  if (!state.turns.length) {
    const empty = node('div','evidence-empty');
    empty.append(node('span','evidence-glyph','⌘'),node('p','','The agent’s actions appear here.'),node('span','','Inspect each tool’s inputs and results before deciding how the conversation went.'));
    root.append(empty);
  }
  state.turns.forEach((turn,index) => {
    const section = node('section','tool-turn');
    const calls = Array.isArray(turn.tool_calls) ? turn.tool_calls : [];
    count += calls.length;
    section.append(node('h3','turn-title','TURN ' + (index+1) + ' · ' + calls.length + (calls.length === 1 ? ' TOOL CALL' : ' TOOL CALLS')));
    if (!calls.length) section.append(node('p','no-tool-note','The agent answered without calling a tool.'));
    calls.forEach((call) => {
      const details = node('details','tool-call');
      const summary = node('summary');
      const result = call.result;
      let decoded = result;
      if (typeof result === 'string') { try { decoded = JSON.parse(result); } catch { /* Keep the actual text. */ } }
      const failed = decoded?.ok === false;
      summary.append(node('span','tool-name',call.name || call.tool_name || 'Tool'),node('span','tool-state' + (failed ? ' error' : ''),failed ? decoded.error || 'Denied' : 'Returned'));
      const payload = node('div','tool-payload');
      payload.append(node('h4','','Arguments'),node('pre','',valueText(call.arguments)),node('h4','','Result'),node('pre','',valueText(result)));
      details.append(summary,payload);
      section.append(details);
    });
    root.append(section);
  });
  $('tool-count').textContent = count;
}

function rememberConversation() {
  try {
    if (state.conversation) sessionStorage.setItem('cartwheel-workbench',JSON.stringify({id:state.conversation.id,expected:$('expected').value,requirement:$('requirement').value,case:state.currentCase,judgement:activeJudgement(),problem_source:$('problem-source').value}));
    else sessionStorage.removeItem('cartwheel-workbench');
  } catch { /* The app also works when browser storage is unavailable. */ }
}

async function restoreConversation() {
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem('cartwheel-workbench') || 'null'); } catch { return; }
  if (!saved?.id) return;
  try {
    const conversation = await api('/api/conversations/' + encodeURIComponent(saved.id));
    state.conversation = { ...conversation, id: conversation.id || saved.id };
    state.turns = conversation.turns || [];
    state.saved = Boolean(conversation.saved);
    state.failed = Boolean(conversation.failed);
    state.currentCase = saved.case || 'custom';
    $('identity').value = conversation.role + ':' + conversation.user_id;
    $('case').value = state.currentCase;
    $('expected').value = conversation.assessment?.expected || saved.expected || conversation.expected || '';
    $('requirement').value = conversation.assessment?.requirement || conversation.requirement || saved.requirement || '';
    state.promptVersion = conversation.prompt_version || state.promptVersion;
    const judgement = typeof conversation.assessment?.met_requirement === 'boolean' ? (conversation.assessment.met_requirement ? 'pass' : 'fail') : saved.judgement;
    if (judgement === 'pass' || judgement === 'fail') document.querySelector('input[name="judgement"][value="' + judgement + '"]').checked = true;
    $('problem-source').value = conversation.assessment?.problem_source || saved.problem_source || '';
    $('failure-field').hidden = activeJudgement() !== 'fail';
    renderChat(); renderEvidence(); updateIdentityHelp(); updateRequirementHelp(); updateControls();
  } catch (error) {
    try { sessionStorage.removeItem('cartwheel-workbench'); } catch { /* No browser storage. */ }
    if (error.status !== 404) showError('request-error','The previous conversation could not be restored. ' + messageFromError(error));
  }
}

function startFresh() {
  if (state.turns.length && !state.saved && !window.confirm('This conversation has not been saved. Start a new conversation?')) return;
  state.conversation = null; state.turns = []; state.saved = false; state.failed = false;
  state.currentCase = 'custom';
  $('case').value = 'custom'; $('request').value = ''; $('expected').value = ''; $('requirement').value = '';
  resetAssessment(); showError('request-error','');
  rememberConversation(); renderChat(); renderEvidence(); updateRequirementHelp(); updateIdentityHelp(); updateControls();
  $('case').focus();
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.busy || state.saving || state.saved || state.failed || !state.status?.ready) return;
  const message = $('request').value.trim();
  const expected = $('expected').value.trim();
  if (!message || !expected) { (!$('expected').value.trim() ? $('expected') : $('request')).focus(); return; }
  state.busy = true;
  showError('request-error',''); showError('save-error','');
  updateControls();
  try {
    if (!state.conversation) {
      const identity = selectedIdentity();
      state.conversation = await api('/api/conversations',{method:'POST',body:JSON.stringify({role:identity.role,user_id:identity.user_id})});
      if (!state.conversation.id && state.conversation.conversation_id) state.conversation.id = state.conversation.conversation_id;
      rememberConversation();
    }
    renderChat(message);
    const result = await api('/api/conversations/' + encodeURIComponent(state.conversation.id) + '/messages',{method:'POST',body:JSON.stringify({message,expected})});
    state.turns = Array.isArray(result.turns) ? result.turns : [...state.turns,{request:message,response:result.reply,tool_calls:result.tool_calls || []}];
    state.promptVersion = result.prompt_version || state.promptVersion;
    $('prompt-label').textContent = state.promptVersion ? 'Prompt ' + String(state.promptVersion).slice(0,8) : '';
    $('request').value = '';
    resetAssessment(); rememberConversation();
    renderChat(); renderEvidence();
  } catch (error) {
    renderChat();
    let detail = messageFromError(error);
    if (error.status === 502) { state.failed = true; resetAssessment(); }
    if (error.status === 409) detail += ' Start a new conversation to continue.';
    showError('request-error',detail);
  } finally {
    state.busy = false; updateControls();
    if (!state.saved) $('request').focus();
  }
}

async function saveConversation(event) {
  event.preventDefault();
  if ($('save-record').disabled || !state.conversation) return;
  const judgement = activeJudgement();
  state.saving = true; showError('save-error',''); updateControls();
  try {
    const result = await api('/api/conversations/' + encodeURIComponent(state.conversation.id) + '/save',{method:'POST',body:JSON.stringify({expected:$('expected').value.trim(),requirement:$('requirement').value || null,met_requirement:judgement === 'pass',problem_source:judgement === 'fail' ? $('problem-source').value : null})});
    if (!result.saved) throw new Error('The server did not confirm that this conversation was saved. Please try again.');
    state.saved = true; renderProgress(result.saved_count);
    $('save-success').textContent = 'Saved with your assessment and the recorded tool evidence.';
    $('save-success').hidden = false; rememberConversation();
  } catch (error) { showError('save-error',messageFromError(error)); }
  finally { state.saving = false; updateControls(); }
}

$('message-form').addEventListener('submit',sendMessage);
$('assessment-form').addEventListener('submit',saveConversation);
$('new-conversation').addEventListener('click',startFresh);
$('refresh-status').addEventListener('click',refreshStatus);
$('request').addEventListener('input',updateControls);
$('request').addEventListener('keydown',(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); if (!$('send-message').disabled) $('message-form').requestSubmit(); } });
$('expected').addEventListener('input',() => { updateControls(); rememberConversation(); });
$('identity').addEventListener('change',() => { updateIdentityHelp(); updateControls(); });
$('requirement').addEventListener('change',() => { updateRequirementHelp(); rememberConversation(); });
$('problem-source').addEventListener('change',() => { updateControls(); rememberConversation(); });
document.querySelectorAll('input[name="judgement"]').forEach((input) => input.addEventListener('change',() => { $('failure-field').hidden = activeJudgement() !== 'fail'; if (activeJudgement() === 'pass') $('problem-source').value = ''; updateControls(); rememberConversation(); }));
$('case').addEventListener('change',() => {
  state.currentCase = $('case').value;
  const preset = cases[state.currentCase];
  $('expected').value = '';
  resetAssessment();
  if (preset) { $('identity').value = preset.identity; $('request').value = preset.message; $('requirement').value = preset.requirement; }
  else { $('request').value = ''; $('requirement').value = ''; }
  updateIdentityHelp(); updateRequirementHelp(); updateControls();
  $('expected').focus();
});

const guide = $('guide-dialog');
$('open-guide').addEventListener('click',() => guide.showModal());
$('close-guide').addEventListener('click',() => guide.close());
$('guide-done').addEventListener('click',() => guide.close());
guide.addEventListener('click',(event) => { if (event.target === guide) { const rect = guide.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) guide.close(); } });

const mobileDownload = $('download-records').cloneNode(true);
mobileDownload.id = 'mobile-download'; mobileDownload.classList.add('mobile-download');
document.querySelector('.review-column').append(mobileDownload);
document.querySelectorAll('.download-link').forEach((link) => link.addEventListener('click',(event) => { if (link.getAttribute('aria-disabled') === 'true') event.preventDefault(); }));
window.addEventListener('beforeunload',(event) => { if (state.busy || state.saving) { event.preventDefault(); event.returnValue = ''; } });

populateRequirements(fallbackRequirements); renderChat(); updateIdentityHelp(); updateControls();
refreshStatus().then(restoreConversation);
