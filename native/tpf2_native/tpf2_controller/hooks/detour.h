#pragma once
#include <atomic>
#include <shared_mutex>
#include <Windows.h>
#include <vector>
#include <unordered_map>

static_assert(sizeof(void*) == 8, "tpf2_controller detours require x64");
static_assert(std::atomic_uint32_t::is_always_lock_free,
	"gateway call counting requires a lock-free 32-bit atomic");


class DetourManager
{
public:
	enum class DetourState : LONG
	{
		Active,
		Draining,
		Uninstalled
	};

	class HookCallGuard
	{
	public:
		~HookCallGuard();
		HookCallGuard(const HookCallGuard&) = delete;
		HookCallGuard& operator=(const HookCallGuard&) = delete;

	private:
		friend class DetourManager;
		explicit HookCallGuard(DetourManager& manager);
		DetourManager* manager_;
	};

	static DetourManager& Instance();
	DetourManager(const DetourManager&) = delete;
	DetourManager& operator=(const DetourManager&) = delete;

	int install_detour(unsigned char* target, const unsigned char* expected, SIZE_T length,
		void* hook, void** original, const char* failure);

	//uninstall all hooks.
	int uninstall_all_detours();
	// The gateway has already incremented the call count. Every installed
	// hook must create this guard at function entry so it is decremented.
	[[nodiscard]] HookCallGuard adopt_hook_call();
	BOOL is_draining() const;


private:

	struct HookTarget
	{
		UINT64* target = nullptr;
		UINT64* original = nullptr;
		UINT64* page = nullptr;
		DWORD start_in_page = 0;
		DWORD length = 0;
	};

	struct TrampolinePage {
		UINT64* page_base = nullptr;
		DWORD length = 0x1000;
		DWORD used_blocks = 0;
		DWORD block_size = 64;
		DWORD left_size = 0x1000;
	};

	struct TrampolineBlock {
		unsigned char gateway[32];
		unsigned char original[32];
	};
	static_assert(sizeof(TrampolineBlock) == 64);

	std::shared_mutex lock_;
	std::atomic_uint32_t active_calls_{ 0 };
	std::atomic<DetourState> state_{ DetourState::Active };

	std::shared_timed_mutex vec_hook_lock;
	std::shared_timed_mutex map_hook_lock;
	std::vector<HookTarget> hooks_;
	std::unordered_map<UINT64*, HookTarget> hookMap_;

	std::shared_timed_mutex vec_page_lock;
	std::shared_timed_mutex map_page_lock;
	std::vector<TrampolinePage> trampolinePages_;
	std::unordered_map<UINT64*, TrampolinePage*> trampolineMap_;

	//ret code 0: success
	//ret code 1: already registered
	//ret code 3: input target is nullptr
	int RegisterHook(UINT64* target, DWORD length = 0);
	BOOL AllocateTrampolinePage(struct HookTarget& bp);
	void leave_hook();
	void wait_for_hook_calls();


	DetourManager();
	~DetourManager();

};
