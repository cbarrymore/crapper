from pathlib import Path

from crapper.analyze import analyze_files
from crapper.coverage import load_bundle
from crapper.discover import is_test_file, language_of
from crapper.languages.csharp import functions_in_source
from crapper.runners import csharp_coverage_command, csharp_solutions

SOURCE = """\
namespace Demo.Risk;

public partial class Calc<T> : Base
{
    public Calc(int x) { if (x > 0 && x < 2) { } }

    public int Score(object o, int[] values)
    {
        foreach (var v in values) { }
        for (var i = 0; i < 3; i++) { }
        while (false) { }
        do { } while (false);
        switch (o) { case 1: case 2: break; default: break; }
        var y = o switch { 1 => 2, _ => 3 };
        try { } catch (Exception) { }
        if (o is int or long) { }
        Func<int, int> f = z => z > 0 ? 1 : 0;
        int Local() => values?.Length ?? 0;
        return y;
    }

    public int Total => _a ? 1 : 2;
    public int Auto { get; set; }
    public int Backed { get => _b ?? 0; set { _b = value; } }
    public int this[int i] => i;
    public static Calc<T> operator +(Calc<T> a, Calc<T> b) => a;
    ~Calc() { }
    public abstract void Abstract();
    partial void Declared();

    class Inner { void Z() { } }
}
"""

BLOCK_NAMESPACES = """namespace Other.Ns
{
    namespace Deep { record struct Point(int X) { int Len() => X; } }
    interface IShape { int Area() { return 0; } void Plain(); }
}
"""


def _by_key():
    found = functions_in_source(SOURCE, "Calc.cs") + functions_in_source(BLOCK_NAMESPACES, "Shapes.cs")
    return {(f.namespace, f.name): f for f in found}


def test_entries_are_members_with_a_body():
    assert set(_by_key()) == {
        ("Demo.Risk.Calc", "Calc"),
        ("Demo.Risk.Calc", "Score"),
        ("Demo.Risk.Calc", "Total"),
        ("Demo.Risk.Calc", "Backed"),
        ("Demo.Risk.Calc", "this[]"),
        ("Demo.Risk.Calc", "operator +"),
        ("Demo.Risk.Calc", "~Calc"),
        ("Demo.Risk.Calc.Inner", "Z"),
        ("Other.Ns.Deep.Point", "Len"),
        ("Other.Ns.IShape", "Area"),
    }


def test_complexity_counts_csharp_decisions():
    found = _by_key()
    # foreach, for, while, do, 3 switch sections, 2 arms, catch, if, or-pattern,
    # lambda ?:, ?. and ?? inside the local function.
    assert found[("Demo.Risk.Calc", "Score")].complexity == 1 + 15
    assert found[("Demo.Risk.Calc", "Calc")].complexity == 3
    assert found[("Demo.Risk.Calc", "Total")].complexity == 2
    assert found[("Demo.Risk.Calc", "Backed")].complexity == 2
    assert found[("Demo.Risk.Calc.Inner", "Z")].complexity == 1


def test_return_type_is_not_taken_for_the_name():
    found = functions_in_source("class A { Foo Bar() { return null; } }", "A.cs")
    assert [(f.namespace, f.name) for f in found] == [("A", "Bar")]


def test_discovery_skips_tests_and_generated_code():
    assert language_of("src/App/Service.cs") == "csharp"
    assert language_of("src/App/Resources.Designer.cs") is None
    assert language_of("obj/Debug/App.g.cs") is None
    assert is_test_file("test/App.UnitTest/ServiceTests.cs")
    assert is_test_file("src/App.Tests/Helper.cs")
    assert not is_test_file("src/App/Latest.cs")


def test_coverlet_lcov_scores_a_function(tmp_path: Path):
    src = tmp_path / "src" / "App"
    src.mkdir(parents=True)
    (src / "Calc.cs").write_text(
        "namespace App;\nclass Calc\n{\n    int Add(int a)\n    {\n        return a;\n    }\n}\n",
        encoding="utf-8",
    )
    report = tmp_path / "target" / "coverage" / "csharp" / "guid"
    report.mkdir(parents=True)
    (report / "coverage.info").write_text(
        f"SF:{src / 'Calc.cs'}\nDA:5,1\nDA:6,1\nDA:7,0\nend_of_record\n", encoding="utf-8"
    )
    entries = analyze_files([src / "Calc.cs"], tmp_path, load_bundle(tmp_path))
    assert [(e.namespace, e.name, round(e.coverage, 1)) for e in entries] == [
        ("App.Calc", "Add", 66.7)
    ]


def test_coverage_runs_once_per_nearest_solution(tmp_path: Path):
    (tmp_path / "Svc.slnx").write_text("<Solution />", encoding="utf-8")
    nested = tmp_path / "src" / "App"
    nested.mkdir(parents=True)
    file = nested / "A.cs"
    file.write_text("class A {}", encoding="utf-8")
    solutions = csharp_solutions(tmp_path, [file, nested / "B.cs"])
    assert solutions == [(tmp_path / "Svc.slnx").resolve()]
    command = csharp_coverage_command(solutions[0], tmp_path / "out")
    assert command[:3] == ["dotnet", "test", str(solutions[0])]
    assert "XPlat Code Coverage;Format=lcov" in command


def test_the_solution_that_lists_the_project_and_its_tests_wins(tmp_path: Path):
    lib = r'Project("{X}") = "Lib", "src\Lib\Lib.csproj", "{Y}"' + "\n"
    tests = r'Project("{X}") = "Lib.Tests", "test\Lib.Tests\Lib.Tests.csproj", "{Z}"' + "\n"
    (tmp_path / "A.Client.sln").write_text(lib, encoding="utf-8")
    (tmp_path / "A.ClientTest.sln").write_text(lib + tests, encoding="utf-8")
    (tmp_path / "B.Other.slnx").write_text(
        '<Solution><Project Path="src/Other/Other.csproj" />'
        '<Project Path="t/O.Tests/O.Tests.csproj" /><Project Path="t/P.Tests/P.Tests.csproj" /></Solution>',
        encoding="utf-8",
    )
    source = tmp_path / "src" / "Lib"
    source.mkdir(parents=True)
    (source / "Lib.csproj").write_text("<Project />", encoding="utf-8")
    assert csharp_solutions(tmp_path, [source / "Calc.cs"]) == [
        (tmp_path / "A.ClientTest.sln").resolve()
    ]
