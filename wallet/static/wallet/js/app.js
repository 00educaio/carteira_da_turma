const state = {
  students: [], movements: [], classes: [], classrooms: [], transferTargets: [],
  selected: null, studentActions: [], selectedActionId: null,
  movementType: "credit", currentClass: null, actionsConfig: null,
  analytics: null, analyticsPeriod: "week", analyticsClassroomId: null,
  analyticsRequest: 0, localBackupChecked: false
};
const $ = (selector) => document.querySelector(selector);
const storageKey = (name) => `classWallet:${document.body.dataset.ownerId}:${name}`;
const initialStudentId = Number(document.body.dataset.initialStudentId) || null;

function csrfToken(){
  return document.cookie.split(";").map(v=>v.trim()).find(v=>v.startsWith("csrftoken="))?.split("=")[1] || "";
}

async function api(url, options={}){
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if ((options.method || "GET") !== "GET") headers["X-CSRFToken"] = csrfToken();
  const response = await fetch(url, { ...options, headers });
  const data = await response.json().catch(()=>({}));
  if(response.status===401){
    const currentPath = `${window.location.pathname}${window.location.search}`;
    window.location.href=`/login/?next=${encodeURIComponent(currentPath)}`;
  }
  if (!response.ok) throw new Error(data.error || "Could not complete the operation.");
  return data;
}

function toast(message){
  const el = $("#toast"); el.textContent = message; el.classList.remove("hidden");
  clearTimeout(toast.timer); toast.timer = setTimeout(()=>el.classList.add("hidden"), 3200);
}

function coins(value){ return `${value} coins`; }
function dateTime(value){ return new Intl.DateTimeFormat("en-US", {dateStyle:"short", timeStyle:"short"}).format(new Date(value)); }

function filteredApiUrl(path, extra={}){
  const params = new URLSearchParams(extra);
  if(state.currentClass !== null) params.set("class_name", state.currentClass);
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}`;
}

function renderClassFilter(){
  const select = $("#classFilter");
  select.innerHTML = `<option value="__all__">All classrooms</option>` + state.classes.map(className=>
    `<option value="${escapeHtml(className)}">${escapeHtml(className || "No classroom")}</option>`
  ).join("");
  select.value = state.currentClass === null ? "__all__" : state.currentClass;
  $("#studentsTitle").textContent = state.currentClass === null
    ? "Students in all classrooms"
    : `Students — ${state.currentClass || "No classroom"}`;
  if(state.currentClass !== null && !$("#studentClass").value) $("#studentClass").value = state.currentClass;
}

function renderClassrooms(){
  const targetOptions = `<option value="">Select</option>` + state.transferTargets.map(user=>
    `<option value="${user.id}">${escapeHtml(user.username)}</option>`
  ).join("");
  $("#classroomsTable").innerHTML = state.classrooms.map(classroom=>`<tr>
    <td data-label="Classroom"><strong>${escapeHtml(classroom.name || "No classroom")}</strong></td>
    <td data-label="Status"><span class="classroom-status ${classroom.active ? "" : "archived"}">${classroom.active ? "Active" : "Archived"}</span></td>
    <td data-label="Students">${classroom.active_student_count} active · ${classroom.student_count} total</td>
    <td data-label="Transfer to"><select class="classroom-transfer" data-id="${classroom.id}" ${state.transferTargets.length ? "" : "disabled"}>${targetOptions}</select></td>
    <td data-label="Actions"><div class="classroom-actions">
      <button class="button primary configure-actions" data-id="${classroom.id}" ${classroom.active ? "" : "disabled"}>Configure actions</button>
      <button class="button ghost rename-classroom" data-id="${classroom.id}">Rename</button>
      <button class="button ghost toggle-classroom" data-id="${classroom.id}">${classroom.active ? "Archive" : "Reactivate"}</button>
      <button class="button secondary transfer-classroom" data-id="${classroom.id}" ${state.transferTargets.length ? "" : "disabled"}>Transfer</button>
    </div></td></tr>`).join("") || `<tr><td colspan="5">No classrooms found.</td></tr>`;

  document.querySelectorAll(".configure-actions").forEach(button=>button.onclick=()=>openActionsConfig(Number(button.dataset.id)));
  document.querySelectorAll(".rename-classroom").forEach(button=>button.onclick=()=>renameClassroom(Number(button.dataset.id)));
  document.querySelectorAll(".toggle-classroom").forEach(button=>button.onclick=()=>toggleClassroom(Number(button.dataset.id)));
  document.querySelectorAll(".transfer-classroom").forEach(button=>button.onclick=()=>transferClassroom(Number(button.dataset.id)));
}

function clearSelectedClass(){
  state.currentClass = null;
  localStorage.setItem(storageKey("selectedClass"), "__all__");
}

async function renameClassroom(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  const name = prompt("New classroom name:", classroom?.name || "");
  if(name===null || !name.trim()) return;
  try{
    await api(`/api/classrooms/${id}/rename/`, {method:"POST", body:JSON.stringify({name})});
    clearSelectedClass(); toast("Classroom renamed."); await loadAll();
  }catch(e){ toast(e.message); }
}

async function toggleClassroom(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  if(!classroom) return;
  const action = classroom.active ? "archive" : "reactivate";
  if(!confirm(`${action[0].toUpperCase()+action.slice(1)} classroom ${classroom.name || "No classroom"}?`)) return;
  try{
    await api(`/api/classrooms/${id}/archive/`, {method:"POST", body:JSON.stringify({active:!classroom.active})});
    clearSelectedClass(); toast(`Classroom ${classroom.active ? "archived" : "reactivated"}.`); await loadAll();
  }catch(e){ toast(e.message); }
}

async function transferClassroom(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  const select = document.querySelector(`.classroom-transfer[data-id="${id}"]`);
  const target = state.transferTargets.find(item=>item.id===Number(select?.value));
  if(!classroom || !target) return toast("Select a destination superuser.");
  if(!confirm(`Transfer ${classroom.name || "No classroom"} and all its data to ${target.username}?`)) return;
  try{
    await api(`/api/classrooms/${id}/transfer/`, {method:"POST", body:JSON.stringify({target_user_id:target.id})});
    clearSelectedClass(); toast("Classroom transferred."); await loadAll();
  }catch(e){ toast(e.message); }
}

function renderActionsConfig(){
  if(!state.actionsConfig) return;
  const groups = [
    {nature:"credit", title:"Rewards", help:"Coins added to the student's balance."},
    {nature:"debit", title:"Expenses", help:"Coins deducted from the balance, even if it becomes negative."}
  ];
  $("#actionsConfigContent").innerHTML = groups.map(group=>{
    const actions = state.actionsConfig.actions.filter(action=>action.nature===group.nature);
    return `<section class="action-config-group">
      <div><h3>${group.title}</h3><p class="help">${group.help}</p></div>
      <div class="action-config-list">${actions.map(action=>`<div class="action-config-row" data-id="${action.id}" data-nature="${action.nature}">
        <label class="action-config-name" for="action-value-${action.id}">${escapeHtml(action.name)}</label>
        <label class="action-value-label">Value (coins)
          <input id="action-value-${action.id}" class="action-value-input" type="number" min="1" step="1" required value="${action.value}">
        </label>
        <label class="action-active-label"><input class="action-active-input" type="checkbox" ${action.active ? "checked" : ""}> Active</label>
      </div>`).join("")}</div>
    </section>`;
  }).join("");
}

async function openActionsConfig(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  if(!classroom?.active) return toast("Only active classrooms can be configured.");
  const panel = $("#actionsConfigPanel");
  $("#actionsConfigTitle").textContent = `Configure actions — ${classroom.name || "No classroom"}`;
  $("#actionsConfigContent").innerHTML = `<p class="help">Loading actions…</p>`;
  panel.classList.remove("hidden");
  panel.scrollIntoView({behavior:"smooth", block:"start"});
  try{
    state.actionsConfig = await api(`/api/classrooms/${id}/actions/`);
    renderActionsConfig();
  }catch(e){
    state.actionsConfig = null;
    $("#actionsConfigContent").innerHTML = `<p class="config-error">${escapeHtml(e.message)}</p>`;
    toast(e.message);
  }
}

async function saveActionsConfig(){
  if(!state.actionsConfig) return;
  const rows = [...document.querySelectorAll(".action-config-row")];
  const actions = [];
  for(const row of rows){
    const input = row.querySelector(".action-value-input");
    const value = Number(input.value);
    if(!input.value.trim() || !Number.isInteger(value) || value <= 0){
      input.focus();
      return toast("Enter whole numbers greater than zero only.");
    }
    actions.push({
      id:Number(row.dataset.id),
      nature:row.dataset.nature,
      value,
      active:row.querySelector(".action-active-input").checked
    });
  }
  const button = $("#saveActionsConfig");
  button.disabled = true;
  try{
    const classroomId = state.actionsConfig.classroom.id;
    const data = await api(`/api/classrooms/${classroomId}/actions/`, {
      method:"POST", body:JSON.stringify({actions})
    });
    state.actionsConfig = data;
    renderActionsConfig();
    toast("Action settings saved.");
    if(state.selected?.classroom_id===classroomId) await loadStudentActions(state.selected.id);
  }catch(e){
    toast(e.message);
  }finally{
    button.disabled = false;
  }
}

function renderStudents(){
  $("#studentsTable").innerHTML = state.students.map(s=>`<tr>
    <td data-label="Student"><strong>${escapeHtml(s.name)}</strong></td><td data-label="Classroom">${escapeHtml(s.class_name || "—")}</td>
    <td data-label="Code"><code>${escapeHtml(s.code)}</code></td><td data-label="Balance" class="balance ${s.balance<0?"negative":""}">${coins(s.balance)}</td>
    <td data-label="Actions"><div class="student-actions"><button class="button ghost select-student" data-id="${s.id}">Use</button><button class="button danger delete-student" data-id="${s.id}">Delete</button></div></td></tr>`).join("") || `<tr><td colspan="5">No students found.</td></tr>`;
  document.querySelectorAll(".select-student").forEach(btn=>btn.onclick=()=>selectStudent(Number(btn.dataset.id)));
  document.querySelectorAll(".delete-student").forEach(btn=>btn.onclick=()=>deleteStudent(Number(btn.dataset.id)));
  renderSearch();
}

async function deleteStudent(id){
  const student = state.students.find(item=>item.id===id);
  if(!student || !confirm(`Delete student ${student.name}?`)) return;
  try{
    await api(`/api/students/${id}/delete/`, {method:"POST", body:"{}"});
    if(state.selected?.id===id){
      state.selected=null;
      state.studentActions=[];
      state.selectedActionId=null;
      $("#selectedStudent").classList.add("hidden");
      $("#movementBox").classList.add("hidden");
      $("#searchInput").value="";
    }
    toast("Student deleted.");
    await loadAll();
  }catch(e){ toast(e.message); }
}

function renderSearch(){
  const q = $("#searchInput").value.trim().toLowerCase();
  const list = q ? state.students.filter(s=>[s.name,s.class_name,s.code].some(v=>(v||"").toLowerCase().includes(q))).slice(0,8) : [];
  $("#searchResults").innerHTML = list.map(s=>`<div class="student-result" data-id="${s.id}"><div><div class="student-name">${escapeHtml(s.name)}</div><div class="student-meta">${escapeHtml(s.class_name || "No classroom")} · Code ${escapeHtml(s.code)}</div></div><div class="balance ${s.balance<0?"negative":""}">${coins(s.balance)}</div></div>`).join("");
  document.querySelectorAll(".student-result").forEach(el=>el.onclick=()=>selectStudent(Number(el.dataset.id)));
}

function renderSelectedStudent(){
  if(!state.selected) return;
  $("#selectedStudent").innerHTML = `<div><div class="student-name">${escapeHtml(state.selected.name)}</div><div class="student-meta">${escapeHtml(state.selected.class_name || "No classroom")} · Code ${escapeHtml(state.selected.code)}</div></div><div class="balance ${state.selected.balance<0?"negative":""}">${coins(state.selected.balance)}</div>`;
}

async function selectStudent(id){
  state.selected = state.students.find(s=>s.id===id) || null;
  if (!state.selected) return;
  state.studentActions = [];
  state.selectedActionId = null;
  renderSelectedStudent();
  $("#selectedStudent").classList.remove("hidden"); $("#movementBox").classList.remove("hidden");
  $("#searchResults").innerHTML = ""; $("#searchInput").value = state.selected.code;
  $("#movementActions").innerHTML = `<p class="help">Loading classroom actions…</p>`;
  await loadStudentActions(id);
}

function renderMovementActions(){
  const actions = state.studentActions.filter(action=>action.active && action.nature===state.movementType);
  if(!actions.some(action=>action.id===state.selectedActionId)) state.selectedActionId = null;
  $("#movementActions").innerHTML = actions.map(action=>`<button type="button" class="movement-action ${action.id===state.selectedActionId?"selected":""}" data-id="${action.id}">
    <span>${escapeHtml(action.name)}</span><strong>${coins(action.value)}</strong>
  </button>`).join("") || `<p class="empty-actions">No active actions in this category. Enable one in the classroom settings.</p>`;
  document.querySelectorAll(".movement-action").forEach(button=>button.onclick=()=>{
    state.selectedActionId = Number(button.dataset.id);
    renderMovementActions();
  });
}

async function loadStudentActions(studentId){
  const selected = state.students.find(student=>student.id===studentId);
  if(!selected) return;
  try{
    const data = await api(`/api/classrooms/${selected.classroom_id}/actions/`);
    if(state.selected?.id!==studentId) return;
    state.studentActions = data.actions;
    state.selectedActionId = null;
    renderMovementActions();
  }catch(e){
    if(state.selected?.id!==studentId) return;
    state.studentActions = [];
    $("#movementActions").innerHTML = `<p class="config-error">${escapeHtml(e.message)}</p>`;
  }
}

function setMovementType(type){
  state.movementType = type;
  state.selectedActionId = null;
  document.querySelectorAll(".segment").forEach(el=>el.classList.toggle("active", el.dataset.type===type));
  renderMovementActions();
}

function renderMovements(){
  $("#movementsTable").innerHTML = state.movements.map(m=>`<tr>
    <td data-label="Date">${dateTime(m.created_at)}</td><td data-label="Student">${escapeHtml(m.student_name)}</td><td data-label="Reason">${escapeHtml(m.reason)}${m.reversed?" · undone":""}</td>
    <td data-label="Amount" class="${m.signed_amount>=0?"amount-positive":"amount-negative"}">${m.signed_amount>=0?"+":""}${coins(m.signed_amount)}</td>
    <td data-label="Balance">${coins(m.balance_after)}</td><td data-label="Actions">${(!m.reversed && ["credit","debit"].includes(m.movement_type))?`<button class="button ghost undo" data-id="${m.id}">Undo</button>`:""}</td></tr>`).join("") || `<tr><td colspan="6">No transactions found.</td></tr>`;
  document.querySelectorAll(".undo").forEach(el=>el.onclick=async()=>{try{await api(`/api/movements/${el.dataset.id}/undo/`,{method:"POST",body:"{}"});toast("Transaction undone.");await loadAll();}catch(e){toast(e.message)}});
}

function renderAnalyticsClassroomFilter(){
  const activeClassrooms = state.classrooms.filter(classroom=>classroom.active);
  if(state.analyticsClassroomId && !activeClassrooms.some(classroom=>classroom.id===state.analyticsClassroomId)){
    state.analyticsClassroomId = null;
  }
  $("#analyticsClassroom").innerHTML = `<option value="">All classrooms</option>` + activeClassrooms.map(classroom=>
    `<option value="${classroom.id}">${escapeHtml(classroom.name || "No classroom")}</option>`
  ).join("");
  $("#analyticsClassroom").value = state.analyticsClassroomId || "";
}

function analyticsLeaderText(items, field, includeClass=false){
  if(!items.length) return "No transactions";
  const names = items.map(item=>includeClass
    ? `${item.name} (${item.class_name || "No classroom"})`
    : item.name
  ).join(", ");
  return `${names} — ${coins(items[0][field])}`;
}

function renderAnalytics(){
  const data = state.analytics;
  if(!data) return;
  const cards = [
    ["Total spent", coins(data.totals.spent), "spent"],
    ["Total earned", coins(data.totals.earned), "earned"],
    ["Highest-spending classroom", analyticsLeaderText(data.leaders.most_spent_classrooms, "spent"), ""],
    ["Lowest-spending classroom", analyticsLeaderText(data.leaders.least_spent_classrooms, "spent"), ""],
    ["Highest-spending student", analyticsLeaderText(data.leaders.most_spent_students, "spent", true), ""],
    ["Highest-earning student", analyticsLeaderText(data.leaders.most_earned_students, "earned", true), ""],
    ["Negative balances", String(data.negative_students.length), "negative"]
  ];
  $("#analyticsCards").innerHTML = cards.map(([label,value,tone])=>`<article class="analytics-card ${tone}">
    <span>${label}</span><strong>${escapeHtml(value)}</strong>
  </article>`).join("");
  $("#analyticsEmpty").classList.toggle("hidden", data.totals.earned!==0 || data.totals.spent!==0);

  $("#analyticsClassroomsTable").innerHTML = data.classrooms.map(item=>`<tr>
    <td data-label="Classroom"><strong>${escapeHtml(item.name || "No classroom")}</strong></td>
    <td data-label="Total earned" class="amount-positive">${coins(item.earned)}</td>
    <td data-label="Total spent" class="amount-negative">${coins(item.spent)}</td>
  </tr>`).join("") || `<tr><td colspan="3">No active classrooms found.</td></tr>`;

  $("#analyticsStudentsTable").innerHTML = data.students.map(item=>`<tr>
    <td data-label="Student"><strong>${escapeHtml(item.name)}</strong></td>
    <td data-label="Classroom">${escapeHtml(item.class_name || "No classroom")}</td>
    <td data-label="Status">${item.active ? "Active" : "Inactive"}</td>
    <td data-label="Total earned" class="amount-positive">${coins(item.earned)}</td>
    <td data-label="Total spent" class="amount-negative">${coins(item.spent)}</td>
  </tr>`).join("") || `<tr><td colspan="5">No students found.</td></tr>`;

  $("#analyticsNegativeTable").innerHTML = data.negative_students.map(item=>`<tr>
    <td data-label="Student"><strong>${escapeHtml(item.name)}</strong></td>
    <td data-label="Classroom">${escapeHtml(item.class_name || "No classroom")}</td>
    <td data-label="Current balance" class="balance negative">${coins(item.balance)}</td>
  </tr>`).join("") || `<tr><td colspan="3">No active students have a negative balance.</td></tr>`;
}

function formatAnalyticsDate(value){
  if(!value) return "";
  const [year,month,day] = value.split("-");
  return `${month}/${day}/${year}`;
}

async function loadAnalytics(){
  const requestId = ++state.analyticsRequest;
  const status = $("#analyticsStatus");
  const error = $("#analyticsError");
  status.textContent = "Loading…";
  status.classList.remove("online");
  error.classList.add("hidden");
  const params = new URLSearchParams({period:state.analyticsPeriod});
  if(state.analyticsClassroomId) params.set("classroom_id", state.analyticsClassroomId);
  if(state.analyticsPeriod==="custom"){
    const start = $("#analyticsStart").value;
    const end = $("#analyticsEnd").value;
    if(!start || !end){
      status.textContent = "Waiting for dates";
      error.textContent = "Enter the start and end dates.";
      error.classList.remove("hidden");
      return;
    }
    params.set("start", start); params.set("end", end);
  }
  try{
    const data = await api(`/api/analytics/?${params}`);
    if(requestId!==state.analyticsRequest) return;
    state.analytics = data;
    renderAnalytics();
    const period = state.analytics.period;
    status.textContent = period.start
      ? `${formatAnalyticsDate(period.start)} to ${formatAnalyticsDate(period.end)}`
      : "All history";
    status.classList.add("online");
  }catch(e){
    if(requestId!==state.analyticsRequest) return;
    state.analytics = null;
    status.textContent = "Error";
    error.textContent = e.message;
    error.classList.remove("hidden");
    $("#analyticsCards").innerHTML = "";
    $("#analyticsClassroomsTable").innerHTML = `<tr><td colspan="3">Could not load the data.</td></tr>`;
    $("#analyticsStudentsTable").innerHTML = `<tr><td colspan="5">Could not load the data.</td></tr>`;
    $("#analyticsNegativeTable").innerHTML = `<tr><td colspan="3">Could not load the data.</td></tr>`;
  }
}

async function maybeRestoreLocalBackup(studentData, classroomData){
  if(state.localBackupChecked) return false;
  state.localBackupChecked = true;
  if(studentData.students.length || classroomData.classrooms.length) return false;
  const stored = localStorage.getItem(storageKey("backup"));
  if(!stored) return false;
  try{
    const backup = JSON.parse(stored);
    await api("/api/restore/", {method:"POST", body:JSON.stringify(backup)});
    toast("The local backup was restored because the server was empty.");
    return true;
  }catch(e){
    toast(`The local backup could not be restored: ${e.message}`);
    return false;
  }
}

async function saveLocalBackup(){
  try{
    const backup = await api("/api/backup/");
    localStorage.setItem(storageKey("backup"), JSON.stringify(backup));
  }catch(_error){
    // Manual downloads and main operations remain available if the browser blocks
    // local storage or does not have enough space for the local copy.
  }
}

async function loadAll(){
  const [studentData, classroomData] = await Promise.all([
    api(filteredApiUrl("/api/students/")),
    api("/api/classrooms/")
  ]);
  state.students = studentData.students;
  state.classes = studentData.classes;
  state.classrooms = classroomData.classrooms;
  state.transferTargets = classroomData.transfer_targets;
  if(await maybeRestoreLocalBackup(studentData, classroomData)) return loadAll();
  if(state.currentClass !== null && !state.classes.includes(state.currentClass)){
    clearSelectedClass();
    return loadAll();
  }
  const movementData = await api(filteredApiUrl("/api/movements/", {limit:100}));
  state.movements = movementData.movements;
  if(state.selected){
    const refreshedStudent = state.students.find(student=>student.id===state.selected.id);
    if(refreshedStudent){
      state.selected = refreshedStudent;
      renderSelectedStudent();
    }else{
      state.selected = null;
      state.studentActions = [];
      state.selectedActionId = null;
      $("#selectedStudent").classList.add("hidden");
      $("#movementBox").classList.add("hidden");
    }
  }
  renderClassFilter(); renderClassrooms(); renderStudents(); renderMovements();
  renderAnalyticsClassroomFilter();
  await loadAnalytics();
  await saveLocalBackup();
  $("#serverStatus").textContent = "Online"; $("#serverStatus").classList.add("online");
  if(studentData.weekly_coins_awarded) toast(`${studentData.weekly_coins_awarded} student(s) received 15 weekly coins.`);
}

function escapeHtml(value){ return String(value ?? "").replace(/[&<>'"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }

$("#searchInput").addEventListener("input", renderSearch);
$("#classFilter").addEventListener("change", async event=>{
  state.currentClass = event.target.value === "__all__" ? null : event.target.value;
  localStorage.setItem(storageKey("selectedClass"), state.currentClass === null ? "__all__" : state.currentClass);
  if(state.currentClass !== null) $("#studentClass").value = state.currentClass;
  try{ await loadAll(); }catch(e){ toast(e.message); }
});
document.querySelectorAll(".segment").forEach(el=>el.onclick=()=>setMovementType(el.dataset.type));
$("#toggleStudentForm").onclick=()=>$("#studentForm").classList.toggle("hidden");
$("#toggleClassManager").onclick=()=>$("#classManager").classList.toggle("hidden");
$("#closeActionsConfig").onclick=()=>{
  state.actionsConfig = null;
  $("#actionsConfigPanel").classList.add("hidden");
};
$("#saveActionsConfig").onclick=saveActionsConfig;
$("#refreshButton").onclick=()=>loadAll().catch(e=>toast(e.message));
$("#analyticsPeriod").onchange=event=>{
  state.analyticsPeriod = event.target.value;
  $("#analyticsCustomDates").classList.toggle("hidden", state.analyticsPeriod!=="custom");
  loadAnalytics();
};
$("#analyticsClassroom").onchange=event=>{
  state.analyticsClassroomId = event.target.value ? Number(event.target.value) : null;
  loadAnalytics();
};
$("#applyAnalyticsFilters").onclick=()=>{
  state.analyticsPeriod = $("#analyticsPeriod").value;
  state.analyticsClassroomId = $("#analyticsClassroom").value
    ? Number($("#analyticsClassroom").value) : null;
  loadAnalytics();
};

$("#createClassButton").onclick=async()=>{try{
  const name=$("#newClassName").value.trim();
  if(!name) return toast("Enter a classroom name.");
  await api("/api/classrooms/",{method:"POST",body:JSON.stringify({name})});
  $("#newClassName").value="";toast("Classroom created.");await loadAll();
}catch(e){toast(e.message)}};

$("#saveStudent").onclick=async()=>{try{
  await api("/api/students/create/",{method:"POST",body:JSON.stringify({name:$("#studentName").value,class_name:$("#studentClass").value,code:$("#studentCode").value})});
  $("#studentName").value="";$("#studentClass").value="";$("#studentCode").value="";toast("Student added.");await loadAll();
}catch(e){toast(e.message)}};

$("#saveBulk").onclick=async()=>{try{
  const data=await api("/api/students/bulk/",{method:"POST",body:JSON.stringify({lines:$("#bulkStudents").value,default_class_name:state.currentClass ?? ""})});
  $("#bulkStudents").value="";toast(`${data.created.length} student(s) added. ${data.errors.length?data.errors.join(" "):""}`);await loadAll();
}catch(e){toast(e.message)}};

$("#confirmMovement").onclick=async()=>{
  if(!state.selected) return toast("Select a student.");
  if(!state.selectedActionId) return toast("Select an action to continue.");
  const studentId = state.selected.id;
  const button = $("#confirmMovement");
  button.disabled = true;
  try{
    await api(`/api/students/${studentId}/movement/`, {
      method:"POST", body:JSON.stringify({action_id:state.selectedActionId})
    });
    toast("Transaction recorded.");
    await loadAll();
    await selectStudent(studentId);
  }catch(e){
    toast(e.message);
  }finally{
    button.disabled = false;
  }
};

$("#resetButton").onclick=async()=>{
  const scope = state.currentClass === null ? "all students in all classrooms" : `all students in ${state.currentClass || "No classroom"}`;
  if(!confirm(`Reset the balance of ${scope}?`))return;
  try{
    const payload = state.currentClass === null ? {} : {class_name:state.currentClass};
    const data=await api("/api/reset/",{method:"POST",body:JSON.stringify(payload)});
    toast(`${data.reset_count} balance(s) reset.`);await loadAll();
  }catch(e){toast(e.message)}
};

$("#restoreInput").onchange=async(event)=>{const file=event.target.files[0];if(!file)return;try{const form=new FormData();form.append("file",file);await api("/api/restore/",{method:"POST",body:form});state.analyticsClassroomId=null;toast("Backup restored.");await loadAll();}catch(e){toast(e.message)}finally{event.target.value=""}};

function waitForImage(image){
  if(image.complete){
    return image.naturalWidth ? Promise.resolve() : Promise.reject(new Error("QR code unavailable."));
  }
  return new Promise((resolve, reject)=>{
    image.addEventListener("load", resolve, {once:true});
    image.addEventListener("error", ()=>reject(new Error("QR code unavailable.")), {once:true});
  });
}

$("#printCardsButton").onclick=async()=>{
  if(!state.students.length) return toast("There are no students to print.");
  const button = $("#printCardsButton");
  const area = document.createElement("section");
  area.id = "printArea";
  area.innerHTML = state.students.map(s=>`<article class="student-card">
    <div class="student-card-details">
      <p class="student-card-label">CLASS WALLET</p>
      <h3>${escapeHtml(s.name)}</h3>
      <p>${escapeHtml(s.class_name||"No classroom")}</p>
      <div class="card-code">${escapeHtml(s.code)}</div>
    </div>
    <figure class="student-card-qr">
      <img src="/api/students/${s.id}/card-qr/" alt="${escapeHtml(s.name)} QR code">
      <figcaption>Scan to add or spend coins</figcaption>
    </figure>
  </article>`).join("");
  document.body.appendChild(area);
  button.disabled = true;
  try{
    await Promise.all([...area.querySelectorAll("img")].map(waitForImage));
    document.body.classList.add("printing-cards");
    await new Promise(resolve=>requestAnimationFrame(resolve));
    window.print();
  }catch(e){
    toast("Could not load the QR codes for printing.");
  }finally{
    document.body.classList.remove("printing-cards");
    area.remove();
    button.disabled = false;
  }
};

setMovementType("credit");
const localToday = new Date(Date.now() - new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
$("#analyticsStart").value = localToday;
$("#analyticsEnd").value = localToday;
const savedClass = localStorage.getItem(storageKey("selectedClass"));
state.currentClass = !initialStudentId && savedClass && savedClass !== "__all__" ? savedClass : null;
loadAll().then(async()=>{
  if(!initialStudentId) return;
  await selectStudent(initialStudentId);
  $(".search-panel").scrollIntoView({behavior:"smooth", block:"start"});
}).catch(e=>{toast(e.message);$("#serverStatus").textContent="Offline";});
