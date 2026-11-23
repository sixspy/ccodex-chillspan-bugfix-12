export const probesViewTemplate = `
<section class="panel">
  <h2>探头登记 · 建批单轨</h2>
  <p class="hint">探头须挂靠仓间；离线探头禁止新建批次。同一探头任一时点最多一笔正式在批，争用必留痕。</p>
  <div class="form-row">
    <div><label>探头编码</label><input v-model="probeForm.probe_code"/></div>
    <div><label>仓间</label>
      <select v-model.number="probeForm.chamber_id">
        <option v-for="c in chambers" :key="c.id" :value="c.id">{{ c.chamber_code }} · {{ c.name }}</option>
      </select>
    </div>
    <div><label>型号</label><input v-model="probeForm.model"/></div>
    <div><label>校准到期</label><input v-model="probeForm.calibration_due" type="date"/></div>
  </div>
  <div class="actions">
    <button @click="registerProbe">登记探头</button>
    <button class="secondary" @click="refresh">刷新</button>
  </div>
  <table class="data-table">
    <thead><tr><th>编码</th><th>仓间</th><th>区域</th><th>在线</th><th>正式在批</th><th>单轨</th><th>争用痕</th><th>到期</th><th></th></tr></thead>
    <tbody>
      <tr v-for="p in probes" :key="p.id" @click="selectProbe(p)">
        <td>{{ p.probe_code }}</td>
        <td>{{ p.chamber_code }}</td>
        <td>{{ p.region }}</td>
        <td><span class="badge" :class="probeOnlineClass(p.online_status)">{{ p.online_status }}</span></td>
        <td>{{ (p.active_batches || []).length }}</td>
        <td><span class="badge" :class="p.single_track_violations ? 'fail' : 'pass'">{{ p.single_track_violations ? '双批违例' : '单轨' }}</span></td>
        <td><span class="badge" :class="p.contention_count ? 'fail' : 'frozen'">{{ p.contention_count || 0 }}</span></td>
        <td>{{ p.calibration_due }}</td>
        <td><button class="mini-btn" @click.stop="loadProbeDetail(p.id)">校准史</button></td>
      </tr>
    </tbody>
  </table>
  <div v-if="probeDetail" class="detail-box">
    <h3>探头 {{ probeDetail.probe.probe_code }}</h3>
    <p>目标温区 {{ probeDetail.probe.target_min }}~{{ probeDetail.probe.target_max }}℃</p>
    <p>正式在批 {{ probeDetail.active_batches.length }} 笔 · 单轨违例 {{ probeDetail.single_track_violations }} · 争用痕 {{ probeDetail.contention.contention_count }} 条
      <span v-if="probeDetail.contention.last_contention" class="hint">（末次：{{ probeDetail.contention.last_contention.actor }} · {{ probeDetail.contention.last_contention.detail }} · {{ probeDetail.contention.last_contention.created_at }}）</span>
    </p>
    <table v-if="probeDetail.active_batches.length" class="data-table compact">
      <thead><tr><th>在批批次</th><th>状态</th><th>代</th></tr></thead>
      <tbody>
        <tr v-for="b in probeDetail.active_batches" :key="b.id">
          <td>{{ b.batch_code }}</td><td>{{ b.status }}</td><td>{{ b.generation }}</td>
        </tr>
      </tbody>
    </table>
    <ul><li v-for="c in probeDetail.calibrations" :key="c.id">{{ c.calibrated_at }} 偏移 {{ c.offset_c }}℃ 至 {{ c.valid_until }}</li></ul>
  </div>
  <h3>争用痕视图（探头建批争用纪）</h3>
  <p class="hint">锁键 probe:{探头ID} 单轨；锁争用与在批拒建同源落 contention_log，无无痕旁路。</p>
  <table class="data-table">
    <thead><tr><th>锁键</th><th>争用方</th><th>动作</th><th>详情</th><th>时间</th></tr></thead>
    <tbody>
      <tr v-for="x in contentionRows" :key="x.id">
        <td>{{ x.lock_key }}</td>
        <td>{{ x.actor }}</td>
        <td><span class="badge fail">{{ x.action }}</span></td>
        <td>{{ x.detail }}</td>
        <td>{{ x.created_at }}</td>
      </tr>
      <tr v-if="!contentionRows.length"><td colspan="5" class="hint">暂无争用记录</td></tr>
    </tbody>
  </table>
</section>
`;
