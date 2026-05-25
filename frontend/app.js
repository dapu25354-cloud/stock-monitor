const BASE_URL = "http://127.0.0.1:8000/api";

function updateTime() {
    document.getElementById("time-tag").innerText = new Date().toLocaleString();
}
setInterval(updateTime, 1000);

async function fetchStocks() {
    const grid = document.getElementById("stock-grid");
    try {
        const resp = await fetch(`${BASE_URL}/stocks`);
        const stocks = await resp.json();
        
        grid.innerHTML = stocks.map(s => `
            <div class="stock-card">
                <div class="signal-badge ${s.signal_type === 'success' ? 'success-bg' : 'normal-bg'}">
                    ${s.signal}
                </div>
                <h3>${s.name} <small style="color:#8b949e">${s.symbol}</small>${s.is_warning ? ' <span style="background:#f0883e;color:#000;padding:1px 6px;border-radius:8px;font-size:0.65rem;margin-left:4px;">⚠️ 警示</span>' : ''}${s.is_state_owned ? ' <span style="background:#1f6feb;color:#fff;padding:1px 6px;border-radius:8px;font-size:0.65rem;margin-left:4px;">🏛️ 官股</span>' : ''}</h3>
                <div class="price">${s.price}</div>
                
                <div class="metric-row">
                    <span>TD 序列:</span>
                    <span class="highlight">${s.td_signal || '無'}</span>
                </div>
                <div class="metric-row">
                    <span>RSI:</span>
                    <span class="${s.rsi < 30 ? 'bull' : (s.rsi > 70 ? 'bear' : '')}">${s.rsi}</span>
                </div>
                <div class="metric-row">
                    <span>20MA 乖離:</span>
                    <span class="${s.bias > 0 ? 'bull' : 'bear'}">${s.bias}%</span>
                </div>
                
                <div class="chip-text">
                    5日 ${s.inst_signal} | 集中度: <span class="highlight">${s.chip_concent}%</span>
                    ${s.today_signal ? `<br/>最近一日 ${s.today_signal}` : ''}
                </div>
                <div class="advice" style="color:#f0f6fc; margin-top:5px; font-weight:bold;">
                    分析: ${s.analysis}
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = "<p>無法連線至後端伺服器，請確認 FastAPI 是否已啟動</p>";
    }
}

async function fetchTodos() {
    const list = document.getElementById("todo-list");
    try {
        const resp = await fetch(`${BASE_URL}/todos`);
        const todos = await resp.json();
        list.innerHTML = todos.map(t => `
            <li>
                <span>${t.task}</span>
                <button class="delete-btn" onclick="deleteTodo(${t.id})">移除</button>
            </li>
        `).join('');
    } catch (e) {}
}

async function addTodo() {
    const input = document.getElementById("todo-input");
    const task = input.value.trim();
    if (!task) return;

    await fetch(`${BASE_URL}/todos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: Date.now(), task: task })
    });
    input.value = "";
    fetchTodos();
}

async function deleteTodo(id) {
    await fetch(`${BASE_URL}/todos/${id}`, { method: "DELETE" });
    fetchTodos();
}

document.getElementById("add-btn").onclick = addTodo;

setInterval(fetchStocks, 60000);

updateTime();
fetchStocks();
fetchTodos();
