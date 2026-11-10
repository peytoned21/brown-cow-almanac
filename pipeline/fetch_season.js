// Run in a signed-in fantasy.espn.com tab. Defines window.BC_FETCH(year) -> compact season JSON.
window.BC_FETCH = async function (y, LID = 125611) {
  const B = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl';
  const hist = y < 2020;
  const url = (views, extra = '') => hist
    ? `${B}/leagueHistory/${LID}?seasonId=${y}&${views}${extra}`
    : `${B}/seasons/${y}/segments/0/leagues/${LID}?${views}${extra}`;
  async function get(u, hdr) {
    for (let i = 0; i < 3; i++) {
      const r = await fetch(u, { credentials: 'include', headers: hdr || {} });
      if (r.ok) { const j = await r.json(); return Array.isArray(j) ? j[0] : j; }
      await new Promise((s) => setTimeout(s, 800));
    }
    throw new Error('fetch failed ' + u);
  }
  const POS = { 1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'D/ST' };
  const base = await get(url('view=mTeam&view=mMatchupScore&view=mSettings&view=mDraftDetail&view=mStatus&view=mRoster'));
  const st = base.settings, ss = st.scheduleSettings;
  const mem = {}; (base.members || []).forEach((m) => { mem[m.id] = ((m.firstName || '') + ' ' + (m.lastName || '')).trim() || m.displayName; });
  const players = {};
  const addP = (p, extra) => { if (!players[p.id]) players[p.id] = [p.fullName, POS[p.defaultPositionId] || '', p.proTeamId || 0, null]; };
  const out = {
    y, name: st.name, done: base.teams.some((t) => t.rankCalculatedFinal === 1),
    curPeriod: base.status ? base.status.currentMatchupPeriod : null,
    settings: {
      reg: ss.matchupPeriodCount, po: ss.playoffTeamCount, poLen: ss.playoffMatchupPeriodLength, seeding: ss.playoffSeedingRule,
      ppr: (st.scoringSettings.scoringItems.find((i) => i.statId === 53) || {}).points || 0,
      passTD: (st.scoringSettings.scoringItems.find((i) => i.statId === 4) || {}).points || 0,
      slots: st.rosterSettings.lineupSlotCounts, divisions: (ss.divisions || []).map((d) => [d.id, d.name]),
      tradeDeadline: st.tradeSettings ? st.tradeSettings.deadlineDate : null, vetoVotes: st.tradeSettings ? st.tradeSettings.vetoVotesRequired : null,
      waivers: st.acquisitionSettings ? st.acquisitionSettings.acquisitionType : null, faab: st.acquisitionSettings ? st.acquisitionSettings.isUsingAcquisitionBudget : null,
      keepers: st.draftSettings ? st.draftSettings.keeperCount : 0, draftType: st.draftSettings ? st.draftSettings.type : null,
    },
    teams: base.teams.map((t) => {
      const o = t.record.overall, tc = t.transactionCounter || {};
      return {
        id: t.id, name: (t.name || ((t.location || '') + ' ' + (t.nickname || ''))).trim(), abbrev: t.abbrev,
        owners: (t.owners || []).map((x) => mem[x] || '?'), div: t.divisionId,
        w: o.wins, l: o.losses, t: o.ties, pf: +o.pointsFor.toFixed(2), pa: +o.pointsAgainst.toFixed(2),
        rank: t.rankCalculatedFinal || 0, seed: t.playoffSeed || 0,
        tc: [tc.acquisitions || 0, tc.drops || 0, tc.trades || 0, tc.moveToActive || 0, tc.acquisitionBudgetSpent || 0],
        roster: ((t.roster && t.roster.entries) || []).map((e) => { addP(e.playerPoolEntry.player); return e.playerId; }),
      };
    }),
    games: (base.schedule || []).filter((s) => s.away).map((s) => [s.matchupPeriodId, s.home.teamId, +(s.home.totalPoints || 0).toFixed(2), s.away.teamId, +(s.away.totalPoints || 0).toFixed(2), s.playoffTierType, s.winner]),
    draft: ((base.draftDetail && base.draftDetail.picks) || []).map((p) => [p.overallPickNumber, p.roundId, p.teamId, p.playerId, p.keeper ? 1 : 0, p.bidAmount || 0]),
    weeks: {}, tx: [],
  };
  // Weekly lineups
  const lastPeriod = Math.max(...out.games.map((g) => g[0]));
  const poLen = ss.playoffMatchupPeriodLength || 1;
  const firstWeek = (mp) => mp <= ss.matchupPeriodCount ? mp : ss.matchupPeriodCount + 1 + (mp - ss.matchupPeriodCount - 1) * poLen;
  const maxMp = out.done ? lastPeriod : Math.min(lastPeriod, (out.curPeriod || 1) - 1);
  for (let mp = 1; mp <= maxMp; mp++) {
    const sp = firstWeek(mp);
    const d = await get(url('view=mBoxscore&view=mMatchupScore', `&scoringPeriodId=${sp}`));
    const rows = [];
    (d.schedule || []).filter((s) => s.matchupPeriodId === mp).forEach((s) => {
      [s.home, s.away].forEach((side) => {
        if (!side) return;
        const R = (poLen === 1 || mp <= ss.matchupPeriodCount) ? (side.rosterForCurrentScoringPeriod || side.rosterForMatchupPeriod) : (side.rosterForMatchupPeriod || side.rosterForCurrentScoringPeriod);
        if (!R) return;
        const full = !!side.rosterForCurrentScoringPeriod;
        rows.push([side.teamId, full ? 1 : 0, R.entries.map((e) => {
          const p = e.playerPoolEntry.player; addP(p);
          const elig = (p.eligibleSlots || []).filter((x) => x < 20).join('.');
          return [e.playerId, full ? e.lineupSlotId : -1, +((e.playerPoolEntry.appliedStatTotal || 0).toFixed(2)), elig];
        })]);
      });
    });
    if (rows.length) out.weeks[mp] = rows;
  }
  // Transactions (2020+)
  if (!hist) {
    const seen = new Set();
    for (let sp = 0; sp <= 18; sp++) {
      const d = await get(url('view=mTransactions2', `&scoringPeriodId=${sp}`));
      (d.transactions || []).forEach((t) => {
        if (seen.has(t.id) || t.status !== 'EXECUTED') return; seen.add(t.id);
        if (!['TRADE_ACCEPT', 'TRADE_UPHOLD', 'TRADE_PROPOSAL', 'FREEAGENT', 'WAIVER'].includes(t.type)) return;
        out.tx.push([t.type, t.scoringPeriodId, t.proposedDate || t.processDate || 0, t.teamId, t.bidAmount || 0,
          (t.items || []).map((i) => [i.type, i.playerId, i.fromTeamId, i.toTeamId])]);
      });
    }
  }
  // Season totals for every relevant player (draft grades, name lookup)
  // Upcoming week: each roster with ESPN's projected points (for matchup previews)
  if (!out.done && out.curPeriod) {
    const mp = out.curPeriod, sp = firstWeek(mp);
    const d = await get(url('view=mRoster', `&scoringPeriodId=${sp}`));
    const up = {};
    (d.teams || []).forEach((t) => {
      up[t.id] = ((t.roster && t.roster.entries) || []).map((e) => {
        const p = e.playerPoolEntry.player; addP(p);
        const pr = (p.stats || []).find((s) => s.scoringPeriodId === sp && s.statSourceId === 1);
        return [e.playerId, e.lineupSlotId, pr && pr.appliedTotal != null ? +pr.appliedTotal.toFixed(1) : 0, (p.eligibleSlots || []).filter((x) => x < 20).join('.'), p.injuryStatus || ''];
      });
    });
    out.upcoming = { mp, sp, teams: up };
  }
  const need = new Set([...out.draft.map((p) => p[3]), ...Object.keys(players).map(Number)]);
  out.tx.forEach((t) => t[5].forEach((i) => need.add(i[1])));
  const kp = await get(url('view=kona_player_info', `&scoringPeriodId=0`), { 'x-fantasy-filter': JSON.stringify({ players: { limit: 1200, sortAppliedStatTotal: { sortAsc: false, sortPriority: 1, value: '00' + y } } }) });
  const ranked = [];
  (kp.players || []).forEach((x) => {
    const p = x.player;
    const s = (p.stats || []).find((q) => q.seasonId === y && q.statSourceId === 0 && q.statSplitTypeId === 0);
    const pts = s && s.appliedTotal != null ? +s.appliedTotal.toFixed(1) : 0;
    ranked.push([p.id, POS[p.defaultPositionId] || '', pts]);
    if (need.has(p.id)) { if (!players[p.id]) players[p.id] = [p.fullName, POS[p.defaultPositionId] || '', p.proTeamId || 0, pts]; else players[p.id][3] = pts; }
  });
  out.ranked = ranked.filter((r) => r[2] > 0).slice(0, 450);
  // fill any drafted players missing a name
  const miss = [...need].filter((id) => !players[id]);
  if (miss.length) {
    const kp2 = await get(url('view=kona_player_info', `&scoringPeriodId=0`), { 'x-fantasy-filter': JSON.stringify({ players: { filterIds: { value: miss }, limit: miss.length } }) });
    (kp2.players || []).forEach((x) => { const p = x.player; if (need.has(p.id) && !players[p.id]) { const s = (p.stats || []).find((q) => q.seasonId === y && q.statSourceId === 0 && q.statSplitTypeId === 0); players[p.id] = [p.fullName, POS[p.defaultPositionId] || '', p.proTeamId || 0, s && s.appliedTotal != null ? +s.appliedTotal.toFixed(1) : 0]; } });
  }
  out.players = players;
  return out;
};
'ready';
