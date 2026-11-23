export const batchesViewTemplate = `
<section class="panel">
  <h2>温控批次入库 · 探头互斥</h2>
  <p class="hint">写入温度点 JSON 数组；同一探头同时只允许一笔正式在批，第二笔零增拒建并写争用痕。</p>
  <div class="form-row">
    <div><label>仓间</label>
      <select v-model.number="batchForm.chamber_id"><option v-for="c in chambers" :key="c.id" :value="c.id">{{ c.chamber_code }}</option></select>
    </div>
    <div><label>探头</label>
      <select v-model.number="batchForm.probe_id"><option v-for="p in batchProbes" :key="p.id" :value="p.id">{{ probeOptionLabel(p) }}</option></select>
    </div>
    <div><label>货载编号</label><input v-model="batchForm.cargo_ref"/></div>
    <div><label>批次编码(可空)</label><input v-model="batchForm.batch_code"/></div>
  </div>
  <div v-if="selectedBatchProbe" class="detail-box">
    探头锁键 <code>probe:{{ selectedBatchProbe.id }}</code> ·
    正式在批 <strong>{{ (selectedBatchProbe.active_batches || []).length }}</strong> 笔 ·
    <span class="badge" :class="selectedBatchProbe.single_track_violations ? 'fail' : 'pass'">{{ selectedBatchProbe.single_track_violations ? '双批违例' : '单轨正常' }}</span>
    · 争用痕 {{ selectedBatchProbe.contention_count || 0 }} 条
    <span v-if="(selectedBatchProbe.active_batches || []).length" class="hint">（在批：{{ selectedBatchProbe.active_batches.map(b => b.batch_code).join('、') }}，再建将 409 拒建）</span>
  </div>
  <label>温度点 JSON</label>
  <textarea v-model="batchForm.points_json" rows="4" placeholder="[{&quot;t&quot;:&quot;08:00&quot;,&quot;c&quot;:-19}]"></textarea>
  <div class="actions">
    <button @click="createBatch">新建批次</button>
    <button class="secondary" @click="refresh">刷新</button>
  </div>
  <table class="data-table">
    <thead><tr><th>批次</th><th>仓间</th><th>探头</th><th>状态</th><th>代</th><th>极值</th><th></th></tr></thead>
    <tbody>
      <tr v-for="b in batches" :key="b.id" @click="selectBatch(b)">
        <td>{{ b.batch_code }}</td>
        <td>{{ b.chamber_code }}</td>
        <td>{{ b.probe_code }}</td>
        <td><span class="badge" :class="statusClass(b.status)">{{ b.status }}</span></td>
        <td>{{ b.generation }}</td>
        <td>{{ fmtTemp(b.min_observed) }} / {{ fmtTemp(b.max_observed) }}</td>
        <td><button class="mini-btn" @click.stop="loadBatchDetail(b.id)">详情</button></td>
      </tr>
    </tbody>
  </table>
  <div v-if="batchDetail" class="detail-box">
    <h3>{{ batchDetail.batch.batch_code }} · {{ batchDetail.batch.cargo_ref }}</h3>
    <p>点数 {{ batchDetail.batch.temp_points.length }} · 游标 {{ batchDetail.excursions.length }} 条</p>
  </div>
</section>
`;
