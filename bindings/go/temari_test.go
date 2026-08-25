// temari_test.go — tests for the temari Go package (requires libtemari.so).
//
// Run from bindings/go:
//
//	cd <temari>/bindings/go && go test ./...
package temari_test

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/WorldObservationLog/Temari/bindings/go"
)

const adam = "1720704575"

func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	// bindings/go/temari_test.go -> <repo>/
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}

func soPath(t *testing.T) string {
	p := os.Getenv("TEMARI_LIB")
	if p == "" {
		p = filepath.Join(repoRoot(), "target", "release", "libtemari.so")
	}
	if _, err := os.Stat(p); err != nil {
		t.Skipf("libtemari.so not found at %s (run `cargo build --release` first)", p)
	}
	return p
}

func data(t *testing.T, ext string) []byte {
	b, err := os.ReadFile(filepath.Join(repoRoot(), "tests", "testdata", "track_"+adam+"_s1."+ext))
	if err != nil {
		t.Fatalf("read testdata: %v", err)
	}
	return b
}

func load(t *testing.T) *temari.Library {
	lib, err := temari.Load(soPath(t))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return lib
}

func TestFromJSONDecrypt(t *testing.T) {
	lib := load(t)
	tmpl, err := lib.FromJSON(data(t, "json"))
	if err != nil {
		t.Fatal(err)
	}
	defer tmpl.Close()
	got, err := tmpl.Decrypt(data(t, "ct"))
	if err != nil {
		t.Fatal(err)
	}
	if !equal(got, data(t, "pt")) {
		t.Fatal("decrypt != expected plaintext")
	}
}

func TestFromJSONInvalid(t *testing.T) {
	lib := load(t)
	if _, err := lib.FromJSON([]byte("{ not json }")); err == nil {
		t.Fatal("expected error for invalid JSON")
	}
}

func TestDecryptPar(t *testing.T) {
	lib := load(t)
	tmpl, err := lib.FromJSON(data(t, "json"))
	if err != nil {
		t.Fatal(err)
	}
	defer tmpl.Close()
	ct := data(t, "ct")
	var chunks [][]byte
	for i := 0; i < len(ct); i += 1024 {
		end := i + 1024
		if end > len(ct) {
			end = len(ct)
		}
		chunks = append(chunks, ct[i:end])
	}
	plains, err := tmpl.DecryptPar(chunks)
	if err != nil {
		t.Fatal(err)
	}
	for i, c := range chunks {
		single, _ := tmpl.Decrypt(c)
		if !equal(plains[i], single) {
			t.Fatalf("batch sample %d != per-sample", i)
		}
	}
}

func TestAllTracksJSON(t *testing.T) {
	lib := load(t)
	td := filepath.Join(repoRoot(), "tests", "testdata")
	files, _ := os.ReadDir(td)
	for _, f := range files {
		if filepath.Ext(f.Name()) != ".json" {
			continue
		}
		base := f.Name()[:len(f.Name())-5]
		body, err := os.ReadFile(filepath.Join(td, f.Name()))
		if err != nil {
			t.Fatal(err)
		}
		tmpl, err := lib.FromJSON(body)
		if err != nil {
			t.Fatalf("%s: FromJSON: %v", base, err)
		}
		ct, _ := os.ReadFile(filepath.Join(td, base+".ct"))
		pt, _ := os.ReadFile(filepath.Join(td, base+".pt"))
		got, err := tmpl.Decrypt(ct)
		if err != nil {
			t.Fatalf("%s: Decrypt: %v", base, err)
		}
		if !equal(got, pt) {
			t.Fatalf("%s: decrypt mismatch", base)
		}
		tmpl.Close()
	}
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

func TestStreamMatchesBatch(t *testing.T) {
	lib := load(t)
	tmpl, err := lib.FromJSON(data(t, "json"))
	if err != nil {
		t.Fatal(err)
	}
	ct := data(t, "ct")
	var chunks [][]byte
	for i := 0; i < len(ct); i += 1024 {
		end := i + 1024
		if end > len(ct) {
			end = len(ct)
		}
		chunks = append(chunks, ct[i:end])
	}
	s, err := tmpl.NewStream(4)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range chunks {
		if err := s.Submit(c); err != nil {
			t.Fatal(err)
		}
	}
	s.Finish()
	var got [][]byte
	for {
		plain, ok := s.Next()
		if !ok {
			break
		}
		got = append(got, plain)
	}
	s.Close()
	tmpl.Close()
	// compare with per-sample decrypts
	tmpl2, _ := lib.FromJSON(data(t, "json"))
	defer tmpl2.Close()
	for i, c := range chunks {
		single, _ := tmpl2.Decrypt(c)
		if !equal(got[i], single) {
			t.Fatalf("stream sample %d != per-sample", i)
		}
	}
}

func TestStreamChannel(t *testing.T) {
	lib := load(t)
	tmpl, _ := lib.FromJSON(data(t, "json"))
	defer tmpl.Close()
	ct := data(t, "ct")
	s, _ := tmpl.NewStream(4)
	for i := 0; i < len(ct); i += 1024 {
		end := i + 1024
		if end > len(ct) {
			end = len(ct)
		}
		s.Submit(ct[i:end])
	}
	s.Finish()
	n := 0
	for range s.C() {
		n++
	}
	s.Close()
	if n == 0 {
		t.Fatal("no plaintexts from C()")
	}
}
