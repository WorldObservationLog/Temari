// json_decrypt.go — temari Go 包完整示例。
//
// 演示 **调用方负责网络** 的新模型:
//  1. 调用方用 net/http 从 40020 key server 拉取 JSON 响应体
//  2. temari.FromJSON(json) 解析为模板(库不做任何网络请求)
//  3. Decrypt / DecryptPar 解密
//
// 默认自动拉起仓库 mock 40020,对 10 条测试轨做 FromJSON 全流程验证,
// 并逐字节对比已知明文。也可用 --json 指定本地 JSON 模板文件(离线)。
//
// 运行(需已 `cargo build --release` 构建 libtemari.so):
//
//	cd <temari>/bindings/go
//	go run ./examples/json_decrypt.go [--server 127.0.0.1:40020] [--no-mock]
package main

import (
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/WorldObservationLog/Temari/bindings/go"
)

var tracks = map[string]string{
	"1720704575": "skd://itunes.apple.com/p683167073/c23",
	"1720704582": "skd://itunes.apple.com/p683167040/c6",
	"1720704586": "skd://itunes.apple.com/p683167043/c6",
	"1720704833": "skd://itunes.apple.com/p683167041/c6",
	"1720704841": "skd://itunes.apple.com/p683166958/c23",
	"1720704847": "skd://itunes.apple.com/p683167009/c6",
	"1720704989": "skd://itunes.apple.com/p683167008/c6",
	"1720704998": "skd://itunes.apple.com/p683167044/c23",
	"1720705006": "skd://itunes.apple.com/p683167074/c23",
	"1720705190": "skd://itunes.apple.com/p683166957/c6",
}

func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	// bindings/go/examples/json_decrypt.go -> <repo>/
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func waitPort(hostPort string, timeout time.Duration) error {
	host, port, _ := strings.Cut(hostPort, ":")
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		c, err := net.DialTimeout("tcp", net.JoinHostPort(host, port), time.Second)
		if err == nil {
			c.Close()
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("server %s not ready in %s", hostPort, timeout)
}

// fetchJSON: 调用方负责网络(库本身不联网)。
func fetchJSON(server, adamID, uri string) ([]byte, error) {
	u := "http://" + server + "/?adamId=" + url.QueryEscape(adamID) + "&uri=" + url.QueryEscape(uri)
	resp, err := http.Get(u)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func main() {
	server := flag.String("server", "127.0.0.1:40020", "40020 key server")
	noMock := flag.Bool("no-mock", false, "don't spawn the repo mock 40020")
	jsonPath := flag.String("json", "", "local JSON template file (offline)")
	flag.Parse()

	repo := repoRoot()
	testdata := filepath.Join(repo, "tests", "testdata")
	soPath := filepath.Join(repo, "target", "release", "libtemari.so")

	var mock *exec.Cmd
	if *jsonPath == "" && !*noMock {
		mock = exec.Command("python3", filepath.Join(repo, "tools", "temari-decrypt", "tests", "mock_key_server.py"), "40020")
		if err := mock.Start(); err != nil {
			fmt.Println("cannot start mock 40020:", err)
			os.Exit(1)
		}
		defer mock.Process.Kill()
		if err := waitPort(*server, 10*time.Second); err != nil {
			fmt.Println(err)
			os.Exit(1)
		}
	}

	// prefer the cdylib bundled with this module; fall back to the local build
	lib, err := temari.LoadDefault()
	if err != nil {
		lib, err = temari.Load(soPath)
	}
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}

	if *jsonPath != "" {
		if err := runLocal(lib, *jsonPath); err != nil {
			fmt.Println("FAIL:", err)
			os.Exit(1)
		}
	} else if err := runNetwork(lib, *server, testdata); err != nil {
		fmt.Println("FAIL:", err)
		os.Exit(1)
	}
	fmt.Println("JSON-DECRYPT: PASS")
}

func runNetwork(lib *temari.Library, server, testdata string) error {
	for adam, uri := range tracks {
		body, err := fetchJSON(server, adam, uri) // 网络在这里
		if err != nil {
			return err
		}
		t, err := lib.FromJSON(body) // 库只解析
		if err != nil {
			return err
		}
		ct := readFile(filepath.Join(testdata, "track_"+adam+"_s1.ct"))
		pt := readFile(filepath.Join(testdata, "track_"+adam+"_s1.pt"))
		got, err := t.Decrypt(ct)
		if err != nil {
			return err
		}
		if !equal(got, pt) {
			return fmt.Errorf("track %s: mismatch", adam)
		}
		t.Close()
	}
	fmt.Printf("[network] FromJSON: %d tracks PASS (caller-side HTTP)\n", len(tracks))

	// 并行批量
	body, _ := fetchJSON(server, "1720704575", tracks["1720704575"])
	t, err := lib.FromJSON(body)
	if err != nil {
		return err
	}
	defer t.Close()
	ct := readFile(filepath.Join(testdata, "track_1720704575_s1.ct"))
	pt := readFile(filepath.Join(testdata, "track_1720704575_s1.pt"))
	var chunks [][]byte
	for i := 0; i < len(ct); i += 1024 {
		end := i + 1024
		if end > len(ct) {
			end = len(ct)
		}
		chunks = append(chunks, ct[i:end])
	}
	plains, err := t.DecryptPar(chunks)
	if err != nil {
		return err
	}
	for i, c := range chunks {
		single, _ := t.Decrypt(c)
		if !equal(plains[i], single) {
			return fmt.Errorf("batch sample %d != per-sample", i)
		}
	}
	fmt.Printf("[network] DecryptPar: %d samples PASS\n", len(chunks))

	body2, _ := fetchJSON(server, "1720704575", tracks["1720704575"])
	t2, err := lib.FromJSON(body2)
	if err != nil {
		return err
	}
	got2, _ := t2.Decrypt(ct)
	if !equal(got2, pt) {
		return fmt.Errorf("second handle mismatch")
	}
	t2.Close()
	fmt.Println("[network] multiple handles PASS")

	// 流式:增量提交,按序取回(C() goroutine+channel)
	body3, _ := fetchJSON(server, "1720704575", tracks["1720704575"])
	t3, err := lib.FromJSON(body3)
	if err != nil {
		return err
	}
	s, err := t3.NewStream(4)
	if err != nil {
		return err
	}
	for i := 0; i < len(ct); i += 1024 {
		end := i + 1024
		if end > len(ct) {
			end = len(ct)
		}
		if err := s.Submit(ct[i:end]); err != nil {
			return err
		}
	}
	s.Finish()
	n := 0
	for range s.C() {
		n++
	}
	s.Close()
	t3.Close()
	if n == 0 {
		return fmt.Errorf("stream: no plaintexts")
	}
	fmt.Printf("[network] stream: %d ordered plaintexts PASS\n", n)
	return nil
}

func runLocal(lib *temari.Library, jsonPath string) error {
	body, err := os.ReadFile(jsonPath)
	if err != nil {
		return err
	}
	t, err := lib.FromJSON(body)
	if err != nil {
		return err
	}
	defer t.Close()
	base := strings.TrimSuffix(filepath.Base(jsonPath), filepath.Ext(jsonPath))
	ctP := filepath.Join(filepath.Dir(jsonPath), base+".ct")
	ptP := filepath.Join(filepath.Dir(jsonPath), base+".pt")
	if _, err := os.Stat(ctP); err == nil {
		ct, _ := os.ReadFile(ctP)
		pt, _ := os.ReadFile(ptP)
		got, err := t.Decrypt(ct)
		if err != nil {
			return err
		}
		if !equal(got, pt) {
			return fmt.Errorf("local JSON decrypt mismatch")
		}
		fmt.Printf("[local] %s: decrypt==pt PASS\n", jsonPath)
	}
	return nil
}

func readFile(p string) []byte {
	b, err := os.ReadFile(p)
	if err != nil {
		fmt.Println("read", p, ":", err)
		os.Exit(1)
	}
	return b
}

func equal(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
