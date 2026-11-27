"""Host values the purchase-order CLI receives at startup.

The command line owns no policy. Identities, read grants, live approver
authority, the linked graph and the bound deployment all come from the
conditional-approval host; this module only names the host-authored callers a
command may act as, so a command can select an identity without embedding a
role, permission or threshold value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from codology import ApprovalAuthorityProvider, DefinitionKey, Principal, ReadGrant
from examples.conditional_approval import declarations as d
from examples.conditional_approval import wiring

CALLERS = ("requester", "approver", "outsider")
RESOURCES: Mapping[str, tuple[DefinitionKey, type[object]]] = {
    "orders": (wiring.ORDER_KEY, d.PurchaseOrder),
    "budgets": (wiring.BUDGET_KEY, d.Budget),
}


@dataclass(frozen=True, slots=True)
class Caller:
    """One host-authored identity a command may act as."""

    name: str
    principal: Principal
    grants: Mapping[DefinitionKey, ReadGrant]
    authority: ApprovalAuthorityProvider


@dataclass(frozen=True, slots=True)
class CliHost:
    """The host-owned deployment, adapters and callers behind one command."""

    host: wiring.Host

    @property
    def path(self) -> Path:
        """The SQLite fixture every command opens."""
        return self.host.path

    def caller(self, name: str) -> Caller:
        """Resolve a host-authored caller; an unknown name is a usage error."""
        if name == "requester":
            return Caller(name, self.host.requester, self.host.grants, self.host.authority)
        if name == "approver":
            return Caller(name, self.host.approver, {}, self.host.authority)
        if name == "outsider":
            return Caller(
                name,
                wiring.outsider(),
                {},
                wiring.HostAuthority(roles=(), permissions=()),
            )
        raise ValueError(f"unknown caller {name!r}.")

    def resource(self, name: str) -> tuple[DefinitionKey, type[object]]:
        """Resolve a resource the host mapped for authorized reads."""
        try:
            return RESOURCES[name]
        except KeyError as error:
            raise ValueError(f"unknown resource {name!r}.") from error


def install(path: Path, *, amount: int, status: str, ceiling: int) -> Path:
    """Create the host fixture and its relay tables at ``path``."""
    return wiring.install(path, amount=amount, status=status, ceiling=ceiling)


def open_host(path: Path) -> CliHost:
    """Open the host over an existing fixture; never create an empty database."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"no database at {target}; run the install command first.")
    return CliHost(wiring.open_host(target))


__all__ = ["CALLERS", "RESOURCES", "Caller", "CliHost", "install", "open_host"]
