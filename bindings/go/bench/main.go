// bench — temari Go 绑定(purego)性能基准, Linux / Windows 通用。
//
// 测三组:
//
//	[1] 单样本吞吐    整轨(9354 B)逐样本解密, MB/s
//	[2] 并行批量吞吐  1 KB/样本, n ∈ {64,256,1024,4096}, MB/s
//	[3] 小样本调用开销 16 B 样本, calls/s 与 us/call
//
// 运行:
//
//	go run ./bench [--lib PATH] [--testdata DIR] [--chunk N]
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"github.com/WorldObservationLog/Temari/bindings/go"
)

const adam = "1720704575"

func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	// bindings/go/bench/main.go -> <repo>/
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func main() {
	lib := flag.String("lib", "", "cdylib path (default: <repo>/target/release auto-detect)")
	testdata := flag.String("testdata", filepath.Join(repoRoot(), "tests", "testdata"), "testdata dir")
	chunk := flag.Int("chunk", 1024, "batch sample size in bytes")
	flag.Parse()

	libPath := *lib
	if libPath == "" {
		libPath = detectLib()
	}
	l, err := temari.Load(libPath)
	if err != nil {
		fmt.Println("load:", err)
		os.Exit(1)
	}
	fmt.Printf("# library: %s\n", libPath)

	tmpl, err := l.FromJSON(readFile(filepath.Join(*testdata, "track_"+adam+"_s1.json")))
	if err != nil {
		fmt.Println("template:", err)
		os.Exit(1)
	}
	defer tmpl.Close()
	ct := readFile(filepath.Join(*testdata, "track_"+adam+"_s1.ct"))
	pt := readFile(filepath.Join(*testdata, "track_"+adam+"_s1.pt"))

	got, err := tmpl.Decrypt(ct)
	if err != nil || !equal(got, pt) {
		fmt.Println("decrypt mismatch (wrong dll/so?)")
		os.Exit(1)
	}
	fmt.Printf("# track %s: %d B, decrypt==pt OK\n", adam, len(ct))
	fmt.Printf("# cores=%d\n", runtime.NumCPU())

	// ---- [1] single-sample throughput ----
	const iters = 3000
	for i := 0; i < 10; i++ {
		tmpl.Decrypt(ct)
	}
	t0 := time.Now()
	for i := 0; i < iters; i++ {
		tmpl.Decrypt(ct)
	}
	dt := time.Since(t0).Seconds()
	fmt.Printf("\n[1] single-sample (%d B): %8.1f MB/s\n", len(ct), float64(len(ct)*iters)/1e6/dt)

	// ---- [2] parallel batch throughput ----
	c := *chunk
	var pool [][]byte
	for i := 0; i+c <= len(ct); i += c {
		pool = append(pool, ct[i:i+c])
	}
	for _, n := range []int{64, 256, 1024, 4096} {
		samples := make([][]byte, n)
		for i := range samples {
			samples[i] = pool[i%len(pool)]
		}
		K := map[int]int{64: 40, 256: 20, 1024: 10, 4096: 4}[n]
		for i := 0; i < 3; i++ {
			tmpl.DecryptPar(samples)
		}
		t0 := time.Now()
		for i := 0; i < K; i++ {
			tmpl.DecryptPar(samples)
		}
		dt := time.Since(t0).Seconds()
		mbps := float64(n*c*K) / 1e6 / dt
		fmt.Printf("[2] batch n=%-5d x %d B: %8.1f MB/s\n", n, c, mbps)
	}

	// ---- [3] small-sample per-call overhead ----
	s16 := ct[:16]
	const N = 200_000
	for i := 0; i < 1000; i++ {
		tmpl.Decrypt(s16)
	}
	t0 = time.Now()
	for i := 0; i < N; i++ {
		tmpl.Decrypt(s16)
	}
	dt = time.Since(t0).Seconds()
	fmt.Printf("[3] 16 B sample: %7.2f M calls/s, %6.2f us/call\n", float64(N)/dt/1e6, dt/float64(N)*1e6)

	// ---- [4] stream: aggregate throughput + C() async ----
	const nStream = 20000
	var streamChunks [][]byte
	for i := 0; i+c <= len(ct); i += c {
		streamChunks = append(streamChunks, ct[i:i+c])
	}
	big := make([][]byte, nStream)
	for i := range big {
		big[i] = streamChunks[i%len(streamChunks)]
	}
	for _, b := range []int{16, 64, 256, 1024} {
		s, err := tmpl.NewStream(b)
		if err != nil {
			fmt.Println("NewStream:", err)
			os.Exit(1)
		}
		t0 := time.Now()
		for _, smp := range big {
			s.Submit(smp)
		}
		s.Finish()
		got := 0
		for {
			if _, ok := s.Next(); !ok {
				break
			}
			got++
		}
		dt := time.Since(t0).Seconds()
		fmt.Printf("[4] stream batch=%-4d n=%d: %8.1f MB/s\n", b, got, float64(nStream*c)/1e6/dt)
		s.Close()
	}
	// C() async channel (end-to-end: timer starts before submit)
	{
		s, _ := tmpl.NewStream(256)
		t0 := time.Now()
		for _, smp := range big {
			s.Submit(smp)
		}
		s.Finish()
		n := 0
		for range s.C() {
			n++
		}
		dt := time.Since(t0).Seconds()
		fmt.Printf("[4] stream C() async batch=256: n=%d %8.1f MB/s\n", n, float64(nStream*c)/1e6/dt)
		s.Close()
	}
}

func detectLib() string {
	repo := repoRoot()
	if p := os.Getenv("TEMARI_LIB"); p != "" {
		return p
	}
	for _, name := range []string{"libtemari.so", "libtemari.dylib", "libtemari.dll", "temari.dll"} {
		p := filepath.Join(repo, "target", "release", name)
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return filepath.Join(repo, "target", "release", "libtemari.so")
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
