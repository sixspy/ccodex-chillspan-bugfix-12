export const reconcileViewTemplate = `
<section class="panel">
  <h2>仓间对账互证 · 探头单轨</h2>
  <div class="form-row">
    <div><label>仓间编码</label><input v-model="reconCode"/></div>
    <div><label>批次互证编码</label><input v-model="proofCode"/></div>
  </div>
  <div class="actions">
    <button @click="loadRecon">对账单仓</button>
    <button class="secondary" @click="loadProof">批次互证</button>
    <button class="secondary" @click="loadReconAll">全仓对账</button>
  </div>
  <div v-if="reconOne" class="detail-box">
    <p>配额 {{ reconOne.quota_batches }} · 在批 {{ reconOne.active_batches }} · <span :class="reconOne.balanced ? 'ok' : 'bad'">{{ reconOne.balanced ? "平衡" : "失衡" }}</span></p>
  </div>
  <div v-if="proofOne" class="detail-box">
    <p>状态 {{ proofOne.status }} · 开放游标 {{ proofOne.open_excursions }} · 温谱 {{ proofOne.spectrum_exports }}</p>
  </div>
  <table class="data-table">
    <thead><tr><th>仓间</th><th>区域</th><th>在批</th><th>余配额</th><th>平衡</th></tr></thead>
    <tbody>
      <tr v-for="r in reconAllItems" :key="r.chamber_code">
        <td>{{ r.chamber_code }}</td>
        <td>{{ r.region }}</td>
        <td>{{ r.active_batches }}</td>
        <td>{{ r.quota_left }}</td>
        <td>{{ r.balanced ? "是" : "否" }}</td>
      </tr>
    </tbody>
  </table>
  <h3>探头建批单轨对账（与争用痕/建批/仓间/封批同源）</h3>
  <div v-if="probeTrackSummary.all_single_track !== undefined" class="detail-box">
    探头 {{ probeTrackSummary.probes }} · 双批违例探头 {{ probeTrackSummary.violation_probes }} · 争用痕合计 {{ probeTrackSummary.contention_total }}
    · <span class="badge" :class="probeTrackSummary.all_single_track ? 'pass' : 'fail'">{{ probeTrackSummary.all_single_track ? '全部单轨' : '存在双批违例' }}</span>
  </div>
  <table class="data-table compact">
    <thead><tr><th>探头ID</th><th>正式在批</th><th>单轨</th><th>争用痕</th></tr></thead>
    <tbody>
      <tr v-for="t in probeTracks" :key="t.probe_id">
        <td>probe:{{ t.probe_id }}</td>
        <td>{{ t.active_batches }}</td>
        <td><span class="badge" :class="t.single_track_ok ? 'pass' : 'fail'">{{ t.single_track_ok ? '单轨' : '双批违例' }}</span></td>
        <td>{{ t.contention_count }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;
