/* Boot: wire each page, then start polling and the websocket. */
(async function () {
  'use strict';
  const WF = window.WF;
  await WF.overviewInit(); // the map must exist before the first data render
  WF.incidentsInit();
  WF.stationsInit();
  WF.maintenanceInit();
  WF.simInit();
  WF.dataqcInit();
  WF.start();
})();
