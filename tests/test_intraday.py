"""Deterministic tests; generated prices below are fixtures, never market data."""
import copy
import datetime as dt
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from intraday import NY, UTC, candidates, ema_points, merge_bars, normalize, parse_yahoo, replay, summary, update_watch
from intraday_server import Monitor, handler_for

def bars(day="2026-11-23", count=40):
    start = int(dt.datetime.fromisoformat(day+"T08:30:00").replace(tzinfo=NY).timestamp())
    return [[start+i*300, 70+i*.05, 70+i*.05+.04, 70+i*.05-.02, 70+i*.05+.02, 100] for i in range(count)]

NOW = dt.datetime(2026,11,24,tzinfo=UTC)

def payload(symbol="CL=F"):
    data=bars()
    return {"chart":{"result":[{"meta":{"symbol":symbol,"instrumentType":"FUTURE","dataGranularity":"5m","currency":"USD","shortName":"TEST FIXTURE"},
             "timestamp":[r[0] for r in data],"indicators":{"quote":[{key:[r[i+1] for r in data] for i,key in enumerate(("open","high","low","close","volume"))}]}}],"error":None}}

class IntradayTests(unittest.TestCase):
    def test_completed_candles_only(self):
        data=bars()
        now=dt.datetime.fromtimestamp(data[12][0]+300,UTC)
        valid, skipped=normalize(data,now)
        self.assertEqual(len(valid),12)  # buffer excludes just-completed bar
        self.assertGreater(skipped,0)
        self.assertFalse(candidates(valid))

    def test_invalid_candles_rejected(self):
        data=bars()
        for changed in ([data[0],data[0]], [[data[0][0]+1,*data[0][1:]]],
                        [[data[0][0],70,69,68,70,100]], [[data[0][0],70,71,69,float("nan"),100]]):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError): normalize(changed,NOW)

    def test_negative_prices_valid_and_null_rows_skipped(self):
        stamp=bars()[0][0]
        valid, skipped=normalize([[stamp,-5,-3,-6,-4,1],[stamp+300,None,None,None,None,0]],NOW)
        self.assertEqual(valid[0][4],-4)
        self.assertEqual(skipped,1)

    def test_zero_volume_is_a_gap(self):
        data=bars();data[8][5]=0
        valid,skipped=normalize(data,NOW)
        self.assertEqual(skipped,1)
        self.assertFalse(candidates(valid))

    def test_provider_identity_and_lengths(self):
        self.assertEqual(len(parse_yahoo(payload(),"CL=F",NOW)["bars"]),40)
        bad=payload();bad["chart"]["result"][0]["meta"]["instrumentType"]="EQUITY"
        with self.assertRaises(ValueError):parse_yahoo(bad,"CL=F",NOW)
        bad=payload();bad["chart"]["result"][0]["indicators"]["quote"][0]["open"].pop()
        with self.assertRaises(ValueError):parse_yahoo(bad,"CL=F",NOW)
        with self.assertRaises(ValueError):parse_yahoo(payload(),"NG=F",NOW)

    def test_first_observation_preserved(self):
        old=bars(count=15);new=bars(count=20)
        new[0][4]=1
        merged=merge_bars(old,new)
        self.assertEqual(merged[0],old[0])
        self.assertEqual(len(merged),20)
        with self.assertRaises(ValueError):merge_bars(new,old)

    def test_next_bar_entry_costs_and_benchmark(self):
        result=replay(bars(),"CL=F")
        trade=result["trades"][0]
        self.assertEqual(trade["entry"],bars()[13][1])
        self.assertEqual(trade["exit"],bars()[25][1])
        self.assertEqual(trade["cost"],25)
        self.assertAlmostEqual(trade["net"],575)
        self.assertEqual(trade["net"],trade["long_net"])

    def test_direction_uses_only_known_closes(self):
        original=candidates(bars())[0]
        changed=bars()
        for row in changed[13:]:
            row[1:5]=[1,2,0,1]
        self.assertEqual(candidates(changed)[0],original)

    def test_warmup_gap_and_missing_exit_excluded(self):
        data=bars();data.pop(8)
        self.assertFalse(candidates(data))
        data=bars();data.pop(20)
        result=replay(data,"CL=F")
        self.assertEqual(result["summary"]["count"],0)
        self.assertEqual(result["excluded"],1)

    def test_dst_anchor(self):
        winter=candidates(bars("2026-11-23"))[0]
        summer=candidates(bars("2026-07-06"))[0]
        self.assertEqual(dt.datetime.fromtimestamp(winter["signal_time"],UTC).hour,14)
        self.assertEqual(dt.datetime.fromtimestamp(summer["signal_time"],UTC).hour,13)

    def test_neutral_and_bad_settings(self):
        data=bars()
        for row in data:row[1:5]=[70,70,70,70]
        self.assertFalse(candidates(data))
        for kwargs in ({"anchor":"09:31"},{"holding":10},{"fee":float("nan")},{"slippage":-1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):replay(bars(),"CL=F",**kwargs)

    def test_drawdown_includes_starting_zero(self):
        result=summary([{"net":-25,"gross":0,"cost":25,"long_net":-25}])
        self.assertEqual(result["max_drawdown"],25)

    def test_no_historical_backfill_in_watch(self):
        self.assertFalse(update_watch([],bars(),"CL=F",NOW,True))

    def test_watch_observation_timing_idempotence_and_frozen_outcome(self):
        now=dt.datetime.fromtimestamp(bars()[14][0]+20,UTC)
        available,_=normalize(bars(),now)
        issued=update_watch([],available,"CL=F",now,True)
        self.assertEqual(len(issued),1)
        self.assertEqual(issued[0]["due_at"],now.timestamp()+3600)
        self.assertEqual(issued[0]["baseline"],available[-1][4])
        again=update_watch(issued,available,"CL=F",now,True)
        self.assertEqual(again,issued)
        resolved=update_watch(issued,bars(),"CL=F",NOW,True)
        self.assertEqual(resolved[0]["status"],"resolved")
        revised=bars()
        for row in revised:row[4]=-20
        self.assertEqual(update_watch(resolved,revised,"CL=F",NOW,False),resolved)

    def test_outage_cannot_issue_and_late_outcome_unscored(self):
        now=dt.datetime.fromtimestamp(bars()[14][0]+20,UTC)
        available,_=normalize(bars(),now)
        self.assertFalse(update_watch([],available,"CL=F",now,False))
        issued=update_watch([],available,"CL=F",now,True)
        self.assertEqual(update_watch(issued,available,"CL=F",NOW,False)[0]["status"],"unscored")

    def test_partial_outage_retains_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            def fetch(symbol,**kwargs):
                if symbol=="NG=F":raise ValueError("TEST OUTAGE")
                return {"bars":bars(),"provider_name":"TEST FIXTURE","skipped":0}
            monitor=Monitor(folder,fetch)
            monitor.states["NG=F"]["bars"]=bars()
            monitor.refresh(NOW)
            self.assertEqual(monitor.states["NG=F"]["status"],"cached")
            self.assertEqual(monitor.states["CL=F"]["status"],"connected")
            self.assertEqual(len(Monitor(folder).states["NG=F"]["bars"]),40)

class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.monitor=Monitor(self.folder.name)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(self.monitor))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.folder.cleanup()
    def request(self,path,headers=None,method="GET"):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port)
        conn.request(method,path,headers=headers or {})
        response=conn.getresponse();status=response.status;body=response.read();conn.close()
        return status,body
    def test_health_and_allowlist(self):
        self.assertEqual(self.request("/api/health")[0],200)
        self.assertEqual(self.request("/.private/CL.json")[0],404)
        self.assertEqual(self.request("/../README.md")[0],404)
    def test_foreign_hosts_origins_and_stop_rejected(self):
        self.assertEqual(self.request("/api/view",{"Host":"example.com"})[0],403)
        self.assertEqual(self.request("/api/view",{"Origin":"https://example.com"})[0],403)
        self.assertEqual(self.request("/api/stop",{"Content-Type":"text/plain"},"POST")[0],403)
        self.assertFalse(self.monitor.stop.is_set())
    def test_invalid_parameters(self):
        self.assertEqual(self.request("/api/view?symbol=AAPL")[0],400)
        self.assertEqual(self.request("/api/view?fee=nan")[0],400)
    def test_public_link_navigation_allowed_but_cross_site_api_denied(self):
        h={"Sec-Fetch-Site":"cross-site","Sec-Fetch-Mode":"navigate"}
        self.assertEqual(self.request("/",h)[0],200)
        self.assertEqual(self.request("/api/view",h)[0],403)

if __name__=="__main__":
    unittest.main()
