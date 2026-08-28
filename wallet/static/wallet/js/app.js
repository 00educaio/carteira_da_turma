const state = {
  students: [], movements: [], classes: [], classrooms: [], transferTargets: [],
  selected: null, studentActions: [], selectedActionId: null,
  movementType: "credit", currentClass: null, actionsConfig: null
};
const $ = (selector) => document.querySelector(selector);
const storageKey = (name) => `classWallet:${document.body.dataset.ownerId}:${name}`;

function csrfToken(){
  return document.cookie.split(";").map(v=>v.trim()).find(v=>v.startsWith("csrftoken="))?.split("=")[1] || "";
}

async function api(url, options={}){
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if ((options.method || "GET") !== "GET") headers["X-CSRFToken"] = csrfToken();
  const response = await fetch(url, { ...options, headers });
  const data = await response.json().catch(()=>({}));
  if(response.status===401) window.location.href=`/login/?next=${encodeURIComponent(window.location.pathname)}`;
  if (!response.ok) throw new Error(data.error || "Não foi possível concluir a operação.");
  return data;
}

function toast(message){
  const el = $("#toast"); el.textContent = message; el.classList.remove("hidden");
  clearTimeout(toast.timer); toast.timer = setTimeout(()=>el.classList.add("hidden"), 3200);
}

function money(value){ return `${value} moedas`; }
function dateTime(value){ return new Intl.DateTimeFormat("pt-BR", {dateStyle:"short", timeStyle:"short"}).format(new Date(value)); }

function filteredApiUrl(path, extra={}){
  const params = new URLSearchParams(extra);
  if(state.currentClass !== null) params.set("class_name", state.currentClass);
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}`;
}

function renderClassFilter(){
  const select = $("#classFilter");
  select.innerHTML = `<option value="__all__">Todas as turmas</option>` + state.classes.map(className=>
    `<option value="${escapeHtml(className)}">${escapeHtml(className || "Sem turma")}</option>`
  ).join("");
  select.value = state.currentClass === null ? "__all__" : state.currentClass;
  $("#studentsTitle").textContent = state.currentClass === null
    ? "Alunos de todas as turmas"
    : `Alunos — ${state.currentClass || "Sem turma"}`;
  if(state.currentClass !== null && !$("#studentClass").value) $("#studentClass").value = state.currentClass;
}

function renderClassrooms(){
  const targetOptions = `<option value="">Selecione</option>` + state.transferTargets.map(user=>
    `<option value="${user.id}">${escapeHtml(user.username)}</option>`
  ).join("");
  $("#classroomsTable").innerHTML = state.classrooms.map(classroom=>`<tr>
    <td data-label="Turma"><strong>${escapeHtml(classroom.name || "Sem turma")}</strong></td>
    <td data-label="Status"><span class="classroom-status ${classroom.active ? "" : "archived"}">${classroom.active ? "Ativa" : "Arquivada"}</span></td>
    <td data-label="Alunos">${classroom.active_student_count} ativo(s) · ${classroom.student_count} total</td>
    <td data-label="Transferir para"><select class="classroom-transfer" data-id="${classroom.id}" ${state.transferTargets.length ? "" : "disabled"}>${targetOptions}</select></td>
    <td data-label="Ações"><div class="classroom-actions">
      <button class="button primary configure-actions" data-id="${classroom.id}" ${classroom.active ? "" : "disabled"}>Configurar ações</button>
      <button class="button ghost rename-classroom" data-id="${classroom.id}">Renomear</button>
      <button class="button ghost toggle-classroom" data-id="${classroom.id}">${classroom.active ? "Arquivar" : "Reativar"}</button>
      <button class="button secondary transfer-classroom" data-id="${classroom.id}" ${state.transferTargets.length ? "" : "disabled"}>Transferir</button>
    </div></td></tr>`).join("") || `<tr><td colspan="5">Nenhuma turma cadastrada.</td></tr>`;

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
  const name = prompt("Novo nome da turma:", classroom?.name || "");
  if(name===null || !name.trim()) return;
  try{
    await api(`/api/classrooms/${id}/rename/`, {method:"POST", body:JSON.stringify({name})});
    clearSelectedClass(); toast("Turma renomeada."); await loadAll();
  }catch(e){ toast(e.message); }
}

async function toggleClassroom(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  if(!classroom) return;
  const action = classroom.active ? "arquivar" : "reativar";
  if(!confirm(`${action[0].toUpperCase()+action.slice(1)} a turma ${classroom.name || "Sem turma"}?`)) return;
  try{
    await api(`/api/classrooms/${id}/archive/`, {method:"POST", body:JSON.stringify({active:!classroom.active})});
    clearSelectedClass(); toast(`Turma ${classroom.active ? "arquivada" : "reativada"}.`); await loadAll();
  }catch(e){ toast(e.message); }
}

async function transferClassroom(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  const select = document.querySelector(`.classroom-transfer[data-id="${id}"]`);
  const target = state.transferTargets.find(item=>item.id===Number(select?.value));
  if(!classroom || !target) return toast("Selecione o superusuário de destino.");
  if(!confirm(`Transferir ${classroom.name || "Sem turma"} e todos os seus dados para ${target.username}?`)) return;
  try{
    await api(`/api/classrooms/${id}/transfer/`, {method:"POST", body:JSON.stringify({target_user_id:target.id})});
    clearSelectedClass(); toast("Turma transferida."); await loadAll();
  }catch(e){ toast(e.message); }
}

function renderActionsConfig(){
  if(!state.actionsConfig) return;
  const groups = [
    {nature:"credit", title:"Recompensas", help:"Moedas adicionadas ao saldo do aluno."},
    {nature:"debit", title:"Despesas", help:"Moedas retiradas do saldo, mesmo que ele fique negativo."}
  ];
  $("#actionsConfigContent").innerHTML = groups.map(group=>{
    const actions = state.actionsConfig.actions.filter(action=>action.nature===group.nature);
    return `<section class="action-config-group">
      <div><h3>${group.title}</h3><p class="help">${group.help}</p></div>
      <div class="action-config-list">${actions.map(action=>`<div class="action-config-row" data-id="${action.id}" data-nature="${action.nature}">
        <label class="action-config-name" for="action-value-${action.id}">${escapeHtml(action.name)}</label>
        <label class="action-value-label">Valor
          <input id="action-value-${action.id}" class="action-value-input" type="number" min="1" step="1" required value="${action.value}">
        </label>
        <label class="action-active-label"><input class="action-active-input" type="checkbox" ${action.active ? "checked" : ""}> Ativa</label>
      </div>`).join("")}</div>
    </section>`;
  }).join("");
}

async function openActionsConfig(id){
  const classroom = state.classrooms.find(item=>item.id===id);
  if(!classroom?.active) return toast("Apenas turmas ativas podem ser configuradas.");
  const panel = $("#actionsConfigPanel");
  $("#actionsConfigTitle").textContent = `Configurar ações — ${classroom.name || "Sem turma"}`;
  $("#actionsConfigContent").innerHTML = `<p class="help">Carregando ações…</p>`;
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
      return toast("Informe somente valores inteiros maiores que zero.");
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
    toast("Configuração de ações salva.");
    if(state.selected?.classroom_id===classroomId) await loadStudentActions(state.selected.id);
  }catch(e){
    toast(e.message);
  }finally{
    button.disabled = false;
  }
}

function renderStudents(){
  $("#studentsTable").innerHTML = state.students.map(s=>`<tr>
    <td data-label="Aluno"><strong>${escapeHtml(s.name)}</strong></td><td data-label="Turma">${escapeHtml(s.class_name || "—")}</td>
    <td data-label="Código"><code>${escapeHtml(s.code)}</code></td><td data-label="Saldo" class="balance ${s.balance<0?"negative":""}">${money(s.balance)}</td>
    <td data-label="Ações"><div class="student-actions"><button class="button ghost select-student" data-id="${s.id}">Usar</button><button class="button danger delete-student" data-id="${s.id}">Apagar</button></div></td></tr>`).join("") || `<tr><td colspan="5">Nenhum aluno cadastrado.</td></tr>`;
  document.querySelectorAll(".select-student").forEach(btn=>btn.onclick=()=>selectStudent(Number(btn.dataset.id)));
  document.querySelectorAll(".delete-student").forEach(btn=>btn.onclick=()=>deleteStudent(Number(btn.dataset.id)));
  renderSearch();
}

async function deleteStudent(id){
  const student = state.students.find(item=>item.id===id);
  if(!student || !confirm(`Apagar o aluno ${student.name}?`)) return;
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
    toast("Aluno apagado.");
    await loadAll();
  }catch(e){ toast(e.message); }
}

function renderSearch(){
  const q = $("#searchInput").value.trim().toLowerCase();
  const list = q ? state.students.filter(s=>[s.name,s.class_name,s.code].some(v=>(v||"").toLowerCase().includes(q))).slice(0,8) : [];
  $("#searchResults").innerHTML = list.map(s=>`<div class="student-result" data-id="${s.id}"><div><div class="student-name">${escapeHtml(s.name)}</div><div class="student-meta">${escapeHtml(s.class_name || "Sem turma")} · Código ${escapeHtml(s.code)}</div></div><div class="balance ${s.balance<0?"negative":""}">${money(s.balance)}</div></div>`).join("");
  document.querySelectorAll(".student-result").forEach(el=>el.onclick=()=>selectStudent(Number(el.dataset.id)));
}

function renderSelectedStudent(){
  if(!state.selected) return;
  $("#selectedStudent").innerHTML = `<div><div class="student-name">${escapeHtml(state.selected.name)}</div><div class="student-meta">${escapeHtml(state.selected.class_name || "Sem turma")} · Código ${escapeHtml(state.selected.code)}</div></div><div class="balance ${state.selected.balance<0?"negative":""}">${money(state.selected.balance)}</div>`;
}

async function selectStudent(id){
  state.selected = state.students.find(s=>s.id===id) || null;
  if (!state.selected) return;
  state.studentActions = [];
  state.selectedActionId = null;
  renderSelectedStudent();
  $("#selectedStudent").classList.remove("hidden"); $("#movementBox").classList.remove("hidden");
  $("#searchResults").innerHTML = ""; $("#searchInput").value = state.selected.code;
  $("#movementActions").innerHTML = `<p class="help">Carregando ações da turma…</p>`;
  await loadStudentActions(id);
}

function renderMovementActions(){
  const actions = state.studentActions.filter(action=>action.active && action.nature===state.movementType);
  if(!actions.some(action=>action.id===state.selectedActionId)) state.selectedActionId = null;
  $("#movementActions").innerHTML = actions.map(action=>`<button type="button" class="movement-action ${action.id===state.selectedActionId?"selected":""}" data-id="${action.id}">
    <span>${escapeHtml(action.name)}</span><strong>${money(action.value)}</strong>
  </button>`).join("") || `<p class="empty-actions">Nenhuma ação ativa nesta categoria. Ative uma opção na configuração da turma.</p>`;
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
    <td data-label="Data">${dateTime(m.created_at)}</td><td data-label="Aluno">${escapeHtml(m.student_name)}</td><td data-label="Motivo">${escapeHtml(m.reason)}${m.reversed?" · desfeito":""}</td>
    <td data-label="Valor" class="${m.signed_amount>=0?"amount-positive":"amount-negative"}">${m.signed_amount>=0?"+":""}${m.signed_amount}</td>
    <td data-label="Saldo">${m.balance_after}</td><td data-label="Ações">${(!m.reversed && ["credit","debit"].includes(m.movement_type))?`<button class="button ghost undo" data-id="${m.id}">Desfazer</button>`:""}</td></tr>`).join("") || `<tr><td colspan="6">Nenhuma movimentação.</td></tr>`;
  document.querySelectorAll(".undo").forEach(el=>el.onclick=async()=>{try{await api(`/api/movements/${el.dataset.id}/undo/`,{method:"POST",body:"{}"});toast("Movimentação desfeita.");await loadAll();}catch(e){toast(e.message)}});
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
  $("#serverStatus").textContent = "Online"; $("#serverStatus").classList.add("online");
  if(studentData.reset_performed) toast("Os saldos foram resetados para a nova semana.");
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

$("#createClassButton").onclick=async()=>{try{
  const name=$("#newClassName").value.trim();
  if(!name) return toast("Informe o nome da turma.");
  await api("/api/classrooms/",{method:"POST",body:JSON.stringify({name})});
  $("#newClassName").value="";toast("Turma criada.");await loadAll();
}catch(e){toast(e.message)}};

$("#saveStudent").onclick=async()=>{try{
  await api("/api/students/create/",{method:"POST",body:JSON.stringify({name:$("#studentName").value,class_name:$("#studentClass").value,code:$("#studentCode").value})});
  $("#studentName").value="";$("#studentClass").value="";$("#studentCode").value="";toast("Aluno cadastrado.");await loadAll();
}catch(e){toast(e.message)}};

$("#saveBulk").onclick=async()=>{try{
  const data=await api("/api/students/bulk/",{method:"POST",body:JSON.stringify({lines:$("#bulkStudents").value,default_class_name:state.currentClass ?? ""})});
  $("#bulkStudents").value="";toast(`${data.created.length} aluno(s) cadastrado(s). ${data.errors.length?data.errors.join(" "):""}`);await loadAll();
}catch(e){toast(e.message)}};

$("#confirmMovement").onclick=async()=>{
  if(!state.selected) return toast("Selecione um aluno.");
  if(!state.selectedActionId) return toast("Selecione uma ação para continuar.");
  const studentId = state.selected.id;
  const button = $("#confirmMovement");
  button.disabled = true;
  try{
    await api(`/api/students/${studentId}/movement/`, {
      method:"POST", body:JSON.stringify({action_id:state.selectedActionId})
    });
    toast("Movimentação registrada.");
    await loadAll();
    await selectStudent(studentId);
  }catch(e){
    toast(e.message);
  }finally{
    button.disabled = false;
  }
};

$("#resetButton").onclick=async()=>{
  const scope = state.currentClass === null ? "todos os alunos de todas as turmas" : `todos os alunos de ${state.currentClass || "Sem turma"}`;
  if(!confirm(`Zerar o saldo de ${scope}?`))return;
  try{
    const payload = state.currentClass === null ? {} : {class_name:state.currentClass};
    const data=await api("/api/reset/",{method:"POST",body:JSON.stringify(payload)});
    toast(`${data.reset_count} saldo(s) resetado(s).`);await loadAll();
  }catch(e){toast(e.message)}
};

$("#restoreInput").onchange=async(event)=>{const file=event.target.files[0];if(!file)return;try{const form=new FormData();form.append("file",file);await api("/api/restore/",{method:"POST",body:form});toast("Backup restaurado.");await loadAll();}catch(e){toast(e.message)}finally{event.target.value=""}};

$("#printCardsButton").onclick=()=>{
  const area=document.createElement("section");area.id="printArea";area.style.cssText="display:grid;grid-template-columns:repeat(2,1fr);gap:18px;padding:20px";
  area.innerHTML=state.students.map(s=>`<article class="student-card"><p>CARTEIRA DA TURMA</p><h3>${escapeHtml(s.name)}</h3><p>${escapeHtml(s.class_name||"Sem turma")}</p><div class="card-code">${escapeHtml(s.code)}</div><p>Apresente este código ao professor.</p></article>`).join("");
  document.body.appendChild(area);document.body.classList.add("printing-cards");window.print();document.body.classList.remove("printing-cards");area.remove();
};

setMovementType("credit");
const savedClass = localStorage.getItem(storageKey("selectedClass"));
state.currentClass = savedClass && savedClass !== "__all__" ? savedClass : null;
loadAll().catch(e=>{toast(e.message);$("#serverStatus").textContent="Offline";});
