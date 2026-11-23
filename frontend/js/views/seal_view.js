export const sealViewTemplate = `
<section class="panel">
  <h2>封批升代 · 探头收口</h2>
  <p class="hint">校准有效且无开放游标时方可封批；封批后该探头正式在批归零、单轨释放，可承接下一批。</p>
  <div class="form-row">
    <div><label>批次</label>
      <select v-model.number="sealForm.batch_id"><option v-for="b in sealableBatches" :key="b.id" :value="b.id">{{ b.batch_code }} · {{ b.probe_code }}</option></select>
    </div>
    <div><label>快照附言</label><input v-model="sealForm.manifest"/></div>
  </div>
  <div class="actions"><button @click="doSeal">执行封批</button></div>
  <table class="data-table">
    <thead><tr><th>批次</th><th>代</th><th>封批时间</th><th>附言摘要</th></tr></thead>
    <tbody>
      <tr v-for="s in seals" :key="s.id">
        <td>{{ s.batch_code }}</td>
        <td>{{ s.batch_generation }}</td>
        <td>{{ s.sealed_at }}</td>
        <td>{{ shortText(s.manifest) }}</td>
      </tr>
    </tbody>
  </table>
  <h3>探头单轨收口态</h3>
  <table class="data-table compact">
    <thead><tr><th>探头</th><th>仓间</th><th>正式在批</th><th>单轨</th><th>争用痕</th></tr></thead>
    <tbody>
      <tr v-for="p in probes" :key="p.id">
        <td>{{ p.probe_code }}</td>
        <td>{{ p.chamber_code }}</td>
        <td>{{ (p.active_batches || []).length }}</td>
        <td><span class="badge" :class="p.single_track_violations ? 'fail' : 'pass'">{{ p.single_track_violations ? '违例' : '单轨' }}</span></td>
        <td>{{ p.contention_count || 0 }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;
